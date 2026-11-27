# SPDX-License-Identifier: LGPL-2.1-or-later
"""Independently authored synthetic CAD acceptance, inside the installed host."""
def check(folder,wait,passed,worker):
    import json
    import subprocess
    import uuid
    import FreeCAD as App
    import Part
    from fcst_app.cad_mesh import package,prepare,validate_receipt,reconcile
    from fcst_app.discretization import seal
    from fcst_host.cad_mesher import CadMesher,geometry,regenerate
    from fcst_host.controller import Session
    from fcst_host.widgets import NativeJob
    from fcst_host import review
    doc=App.newDocument('SyntheticCadAcceptance')
    solid=doc.addObject('PartDesign::Feature','SyntheticSolid');solid.Shape=Part.makeBox(1000,500,250)
    identifier=str(uuid.uuid4());jobs=[]
    card=dict(density=dict(value=2,unit='kg/m3'),specific_heat=dict(value=3,unit='J/(kg*K)'),
        conductivity=dict(value=1,unit='W/(m*K)'),temperature=dict(value=350,unit='K'),thickness=dict(value=10,unit='mm'))
    def wait_mesh(job):
        job.start()
        wait(lambda:job.state not in ('prepared','running'),seconds=125)
        assert job.state=='succeeded',(job.state,job.error)
        assert job.process.exitCode()==0
        return job

    def mesh(part,dimension,size,previous=None):
        directory=folder/('cad-'+uuid.uuid4().hex);directory.mkdir()
        job=(CadMesher(part,identifier,directory,dimension=dimension,maximum_size_m=size) if previous is None
             else regenerate(part,previous,directory,maximum_size_m=size))
        return wait_mesh(job)

    previous=None
    for size in (.5,.25,.125):
        job=mesh(solid,3,size,previous);jobs.append(job)
        faces=job.source['geometry']['faces']
        # Explicit host FaceN selection; no coordinate-based identity matching.
        left=next(f for f in faces if abs(solid.Shape.getElement(f['ref']).CenterOfMass.x)<1e-8)
        right=next(f for f in faces if abs(solid.Shape.getElement(f['ref']).CenterOfMass.x-1000)<1e-8)
        boundary=[dict(face_id=left['id'],kind='temperature',value=dict(value=300,unit='K')),
            dict(face_id=right['id'],kind='total_power',value=dict(value=10,unit='W'))]
        value,receipt=prepare(job.source,job.brep,{'Solid1':card},boundary)
        if previous is not None:
            assert job.synchronization==dict(status='synchronized',geometry_changed=False,mesh_changed=True)
            assert job.prepared_project.model==value['model']
        previous=package(receipt,job.brep) if previous is None else job.prepared_project
        assert abs(receipt['assignments'][0]['integrated_power_W']-10)<1e-12
        output=subprocess.run([worker,'--thermal-steady'],input=json.dumps(seal(value)).encode(),capture_output=True,timeout=30)
        assert output.returncode==0
        result=json.loads(output.stdout);assert result['status']=='passed' and abs(result['energy_defect_W'])<1e-8
        temperatures={n['node_id']:n['temperature_K'] for n in result['nodes']}
        for p in value['spatial']['points']:
            assert abs(temperatures[p['node_id']]-(300+80*p['position'][0]))<1e-7
        # Constant-gradient patch is an independent Fourier solution on every
        # genuinely generated unstructured refinement, including its boundaries.
        evaluation=subprocess.run([worker,'--spatial-evaluate'],input=json.dumps(dict(thermal_input=seal(value),
            temperature_K=[temperatures[n] for n in sorted(temperatures)])).encode(),capture_output=True,timeout=30)
        assert evaluation.returncode==0
        fields=json.loads(evaluation.stdout)
        for cell in fields['cells']:
            assert max(abs(a-b) for a,b in zip(cell['heat_flux_W_per_m2'],[-80,0,0]))<1e-6
        assert validate_receipt(receipt,job.brep)==seal(value)
    assert [len(j.source['nodes']) for j in jobs]==sorted({len(j.source['nodes']) for j in jobs})
    assert jobs[0].source['geometry']==jobs[-1].source['geometry']
    coarse,coarse_receipt=prepare(jobs[0].source,jobs[0].brep,{'Solid1':card})
    fine,fine_receipt=prepare(jobs[-1].source,jobs[-1].brep,{'Solid1':card})
    assert coarse_receipt['mesh_revision']!=fine_receipt['mesh_revision']
    assert not {p['node_id'] for p in coarse['spatial']['points']}&{p['node_id'] for p in fine['spatial']['points']}
    # Actual changed host topology: split, merge, reorder, delete. Each requires
    # an explicit new acceptance; a face signature/row is never silently rebound.
    original=solid.Shape
    changed=[Part.makeCompound([Part.makePlane(500,500),Part.makePlane(500,500,App.Vector(500,0,0))]),
        Part.makeBox(1000,500,500),Part.makeCompound(list(reversed(original.Faces))),Part.makeCompound(original.Faces[:-1])]
    for shape in changed:
        descriptor=geometry(shape,identifier,0,shape.exportBrepToString().encode())
        try:reconcile(fine_receipt,descriptor)
        except ValueError:pass
        else:raise AssertionError('cad_topology_reassigned')
    passed('FEM-REUSE-003')
    shell=doc.addObject('PartDesign::Feature','SyntheticShell');shell.Shape=Part.makePlane(1000,500)
    shell_job=mesh(shell,2,.25)
    shell_value,_=prepare(shell_job.source,shell_job.brep,{'Face1':card})
    assert all(c['topology']=='tri3' and c['thickness_m']==.01 for c in shell_value['spatial']['cells'])
    assert abs(sum(e['capacity']['value'] for e in shell_value['model']['entities'] if e['kind']=='node')-.03)<1e-10
    curved=doc.addObject('PartDesign::Feature','SyntheticCylinder');curved.Shape=Part.makeCylinder(250,1000)
    cylinder=mesh(curved,3,.25);prepare(cylinder.source,cylinder.brep,{'Solid1':card})
    multiple=doc.addObject('PartDesign::Feature','SyntheticRegions')
    multiple.Shape=Part.makeCompound([Part.makeBox(250,250,250),Part.makeBox(250,250,250,App.Vector(500,0,0))])
    regions=mesh(multiple,3,.25)
    second={**card,'conductivity':dict(value=2,unit='W/(m*K)')}
    multi,_=prepare(regions.source,regions.brep,{'Solid1':card,'Solid2':second})
    assert len({e['material_id'] for e in multi['model']['entities'] if e['kind']=='element'})==2
    passed('WP16-CAD-PROFILES')
    # Installed-workbench solve, exterior-face contour, original geometry and
    # immutable receipt survive portable save/reopen without running the mesher.
    session=Session.from_cad(folder/'cad-session',receipt,job.brep)
    session.options={**review.DEFAULT_SETTINGS,'mode':'steady'}
    native=NativeJob(session,worker);session.job=native;native.start()
    wait(lambda:native.state not in ('queued','running'))
    assert native.state=='succeeded' and session.discretization_view.mesh.FemMesh.FaceCount==len(job.source['facets'])
    session.save(folder/'cad.FCStd',folder/'cad.fcst');session.close();App.closeDocument(session.doc.Name)
    session=Session.open(folder/'cad.fcst',folder/'cad-reopened')
    assert session.thermal_input==value and session.result is not None
    assert session.objects[identifier].Shape.isValid()
    session.close();App.closeDocument(session.doc.Name)
    passed('WP16-CAD-PERSISTENCE')
    import FreeCADGui as Gui
    from PySide6 import QtCore,QtWidgets,QtTest
    from fcst_host.cad_dialog import open_selected
    from fcst_host import workbench
    App.setActiveDocument(doc.Name);Gui.Selection.clearSelection();Gui.Selection.addSelection(solid)
    dialog=open_selected();dialog.findChild(QtWidgets.QDoubleSpinBox,'FCSTCad_size').setValue(.5)
    outcome=[];dialog.finished.connect(outcome.append)
    ticks=[];timer=QtCore.QTimer();timer.timeout.connect(lambda:ticks.append(True));timer.start(1)
    QtTest.QTest.mouseClick(dialog.findChild(QtWidgets.QDialogButtonBox).button(QtWidgets.QDialogButtonBox.Ok),QtCore.Qt.LeftButton)
    wait(lambda:bool(outcome));timer.stop()
    assert outcome==[QtWidgets.QDialog.Accepted] and ticks
    created=workbench.current();assert created.thermal_input is not None
    created.close();App.closeDocument(created.doc.Name);App.closeDocument(doc.Name)
    passed('WP16-CAD-COMMAND')
