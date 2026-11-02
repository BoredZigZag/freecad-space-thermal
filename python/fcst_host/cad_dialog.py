# SPDX-License-Identifier: LGPL-2.1-or-later
"""Selected CAD to native thermal project, using the pinned asynchronous mesher."""
from pathlib import Path
import tempfile
import uuid

from fcst_app.persistence import reject
from fcst_contracts import loads


def open_selected():
    import FreeCADGui as Gui
    from PySide6 import QtCore,QtWidgets
    from .cad_mesher import CadMesher
    from .controller import Session
    from .widgets import diagnostic
    from .workbench import show
    from fcst_app.cad_mesh import prepare
    selected=Gui.Selection.getSelection()
    if len(selected)!=1 or not hasattr(selected[0],'Shape'):reject('select_one_cad_object')
    part=selected[0];dimension=3 if part.Shape.Solids else 2
    dialog=QtWidgets.QDialog(Gui.getMainWindow());dialog.setWindowTitle('Mesh CAD thermal model')
    dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    dialog.setObjectName('FCSTCadMesher');lifecycle={'closed':False}
    layout=QtWidgets.QFormLayout(dialog);fields={}
    for name,label,default in [('size','Maximum mesh size (m)',.25),('density','Density (kg/m3)',2700),
            ('specific_heat','Specific heat (J/kg/K)',900),('conductivity','Conductivity (W/m/K)',200),
            ('temperature','Initial temperature (K)',300),('thickness','Shell thickness (m)',.01)]:
        widget=QtWidgets.QDoubleSpinBox();widget.setDecimals(6);widget.setRange(.000001,1e9);widget.setValue(default)
        fields[name]=widget;layout.addRow(label,widget)
        widget.setObjectName('FCSTCad_'+name)
    fields['thickness'].setEnabled(dimension==2)
    conditions=QtWidgets.QPlainTextEdit();conditions.setPlainText('[]')
    conditions.setObjectName('FCSTCadConditions')
    conditions.setPlaceholderText('[{"face_ref":"Face1","kind":"temperature","value":{"value":300,"unit":"K"}}]')
    layout.addRow('Face conditions (JSON; FaceN references)',conditions)
    status=QtWidgets.QLabel('Unassigned exterior faces are adiabatic.');layout.addRow(status)
    buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel);layout.addRow(buttons)
    dialog.job=None
    def cancel():
        if dialog.job:dialog.job.cancel()
        dialog.reject()
    def start():
        try:
            if dialog.job:reject('cad_mesher_state')
            boundaries=loads(conditions.toPlainText().encode())
            if not isinstance(boundaries,list):reject('cad_boundary_card')
            directory=Path(tempfile.mkdtemp(prefix='fcst-cad-'))
            job=CadMesher(part,str(uuid.uuid4()),directory,dimension=dimension,maximum_size_m=fields['size'].value())
            dialog.job=job
            card={k:dict(value=fields[k].value(),unit=unit) for k,unit in [('density','kg/m3'),('specific_heat','J/(kg*K)'),
                ('conductivity','W/(m*K)'),('temperature','K'),('thickness','m')]}
            def finished(job):
                if lifecycle['closed']:return
                try:
                    if job.state!='succeeded':reject(job.error or 'cad_mesher_process')
                    faces={f['ref']:f['id'] for f in job.source['geometry']['faces']};mapped=[]
                    for entry in boundaries:
                        if not isinstance(entry,dict) or entry.get('face_ref') not in faces:reject('cad_boundary_selection')
                        mapped.append({**{k:v for k,v in entry.items() if k!='face_ref'},'face_id':faces[entry['face_ref']]})
                    _,receipt=prepare(job.source,job.brep,{r:card for r in {c['region'] for c in job.source['cells']}},mapped)
                    session=Session.from_cad(Path(tempfile.mkdtemp(prefix='fcst-host-')),receipt,job.brep)
                    show(session);dialog.accept()
                except (ValueError,OSError):status.setText('Mesh preparation failed; check face conditions and CAD topology.')
            status.setText('Meshing…');buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False);job.start(finished)
        except (ValueError,OSError) as error:status.setText(diagnostic(error))
    buttons.accepted.connect(start);buttons.rejected.connect(cancel)
    def closed(_):
        lifecycle['closed']=True
        if dialog.job:dialog.job.cancel()
    dialog.finished.connect(closed)
    dialog.show();return dialog
