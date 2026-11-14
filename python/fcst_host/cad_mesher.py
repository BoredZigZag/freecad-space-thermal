# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pinned FEM Gmsh API adapter; only immutable SI values leave the host thread."""
from hashlib import sha256
from functools import partial
import math
from pathlib import Path
import re
import uuid

from fcst_app.fem_adapter import assert_thread
from fcst_app.persistence import reject
from fcst_app.cad_mesh import profile,profile_hash
from fcst_contracts import read
from .controller import shape_signature


def geometry(shape,identifier,revision,brep):
    identifier=str(uuid.UUID(identifier))
    return dict(id=identifier,revision=revision,brep_sha256=sha256(brep).hexdigest(),signature=shape_signature(shape),
        faces=[dict(id=str(uuid.uuid5(uuid.UUID(identifier),f'face:{i}:{shape_signature(face)}')),
            ref=f'Face{i}',signature=shape_signature(face),area_m2=face.Area*1e-6) for i,face in enumerate(shape.Faces,1)])


def regenerate(part, previous_project, workspace, *, maximum_size_m=None,
               minimum_size_m=None, region_map=None, face_map=None):
    """Run the pinned mesher and transfer accepted assignments on success."""
    from fcst_app.cad_mesh import synchronize_project
    from fcst_contracts import loads, read

    raw = previous_project.files.get('cad-mesh/prepared.json')
    if raw is None:
        reject('td_cad_sync_project')
    old = read('cad_mesh', loads(raw)['source'])
    options = old['options']
    if maximum_size_m is None:
        maximum_size_m = options['maximum_size_m']
        if minimum_size_m is None:
            minimum_size_m = options['minimum_size_m']
    prepare_mesh = partial(synchronize_project, previous_project, region_map=region_map, face_map=face_map)
    return CadMesher(part, old['geometry']['id'], workspace, revision=int(old['geometry']['revision']),
                     dimension=int(options['dimension']), maximum_size_m=maximum_size_m,
                     minimum_size_m=minimum_size_m, prepare_mesh=prepare_mesh)


class CadMesher:
    """One bounded asynchronous job, with explicit cancellation and topology guard.

    The caller owns an empty private working directory. Generated BREP/UNV/geo
    files and raw diagnostics remain there, outside the portable receipt.
    """
    def __init__(self,part,identifier,workspace,*,dimension=3,maximum_size_m=.25,minimum_size_m=None,revision=0,
                 prepare_mesh=None):
        assert_thread()
        import FreeCAD as App
        import ObjectsFem
        from femmesh.gmshtools import GmshTools
        from PySide6 import QtCore
        self.part=part;self.identifier=identifier;self.revision=revision
        self.prepare_mesh=prepare_mesh; self.prepared_project=None; self.synchronization=None
        self.directory=Path(workspace).resolve()
        if not self.directory.is_dir() or any(self.directory.iterdir()):reject('cad_mesher_workspace')
        minimum_size_m=maximum_size_m if minimum_size_m is None else minimum_size_m
        if (type(dimension) is not int or dimension not in (2,3) or any(type(x) not in (int,float) or not math.isfinite(x) or x<=0
                for x in (maximum_size_m,minimum_size_m)) or minimum_size_m>maximum_size_m):reject('cad_mesh_options')
        if not part.Shape.isValid() or (dimension==3 and not part.Shape.Solids) or (dimension==2 and part.Shape.Solids):reject('unsupported_cad_shape')
        self.signature=shape_signature(part.Shape);self.placement=str(part.getGlobalPlacement())
        self.options=dict(profile()['options'],dimension=dimension,maximum_size_m=maximum_size_m,minimum_size_m=minimum_size_m)
        home=Path(App.getHomePath())
        for name,digest in profile()['files'].items():
            if sha256((home/name).read_bytes()).hexdigest()!=digest:reject('cad_mesher_source_lock')
        self.mesh=ObjectsFem.makeMeshGmsh(part.Document,'FCSTCadMesh');self.mesh.Shape=part
        properties=dict(profile()['host_properties'],CharacteristicLengthMax=maximum_size_m*1000,
            CharacteristicLengthMin=minimum_size_m*1000,ElementDimension=f'{dimension}D',WorkingDirectory=str(self.directory))
        for name,value in properties.items():setattr(self.mesh,name,value)
        self.tool=GmshTools(self.mesh);self.tool.update_mesh_data();self.tool.get_tmp_file_paths(str(self.directory))
        self.tool.gmsh_bin=str(home/'bin/gmsh.exe');self.tool.write_gmsh_input_files()
        self.brep=Path(self.tool.temp_file_geometry).read_bytes()
        # The upstream writer owns topology and group translation. Pin only the
        # selected execution profile, rejecting unexpected upstream script layout.
        path=Path(self.tool.temp_file_geo);script=path.read_text()
        script,count=re.subn(r'General\.NumThreads = [0-9]+;', 'General.NumThreads = 1;',script)
        if count!=1 or len(re.findall(r'^Mesh  [23];$',script,re.M))!=1:reject('cad_mesher_api_changed')
        script=re.sub(r'^(Mesh  [23];)$',r'Mesh.RandomSeed = 1;\n\1',script,flags=re.M)
        path.write_text(script,encoding='utf-8')
        self.process=self.tool.process;self.process.setWorkingDirectory(str(self.directory))
        environment=QtCore.QProcessEnvironment()
        import os
        for name in ('SystemRoot','WINDIR'):
            if name in os.environ:environment.insert(name,os.environ[name])
        for name in ('HOME','USERPROFILE','APPDATA','TEMP','TMP'):environment.insert(name,str(self.directory))
        environment.insert('PATH',str(home/'bin'));environment.insert('OMP_NUM_THREADS','1')
        self.process.setProcessEnvironment(environment)
        self.process.setStandardOutputFile(str(self.directory/'mesher.log'))
        self.process.setStandardErrorFile(str(self.directory/'mesher-error.log'))
        self.timer=QtCore.QTimer();self.timer.setSingleShot(True);self.timer.timeout.connect(self.cancel)
        self.state='prepared';self.error=None;self.source=None;self.on_finished=None;self.notified=False
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)

    def start(self,on_finished=None):
        assert_thread()
        if self.state!='prepared':reject('cad_mesher_state')
        self.on_finished=on_finished;self.state='running';self.timer.start(120000)
        self.process.start(self.tool.gmsh_bin,['-nopopup','-v','2','-',self.tool.temp_file_geo])

    def cancel(self):
        assert_thread()
        if self.state=='running':
            self.state='cancelled';self.error='cad_mesher_cancelled';self.process.kill()

    def _error(self,error):
        if self.state=='running':
            self.state='failed';self.error='cad_mesher_process';self.timer.stop();self._notify()

    def _notify(self):
        if not self.notified:
            self.notified=True
            if self.on_finished:self.on_finished(self)

    def _finished(self,code,status):
        self.timer.stop()
        if self.state=='running':
            try:
                if code!=0:reject('cad_mesher_process')
                if shape_signature(self.part.Shape)!=self.signature or str(self.part.getGlobalPlacement())!=self.placement:
                    reject('attachment_reassignment_required')
                if not self.mesh.FemMesh.NodeCount:self.tool.update_properties()
                source=self.extract()
                if self.prepare_mesh is not None:
                    self.prepared_project,self.synchronization=self.prepare_mesh(source,self.brep)
                self.source=source;self.state='succeeded'
            except (ValueError,RuntimeError,ReferenceError):self.state='failed';self.error='cad_mesher_output_or_topology'
        self._notify()

    def extract(self):
        assert_thread()
        import Part
        # GmshTools exports global-placement BREP. Use exactly those bytes for
        # geometry identity, face signatures, coordinates and portable reopening.
        shape=Part.Shape();shape.importBrepFromString(self.brep.decode('ascii'))
        descriptor=geometry(shape,self.identifier,self.revision,self.brep)
        mesh=self.mesh.FemMesh;groups={mesh.getGroupName(g):list(mesh.getGroupElements(g)) for g in mesh.Groups}
        tags=list(mesh.Volumes if self.options['dimension']==3 else mesh.Faces)
        owner={}
        for name,items in groups.items():
            if re.fullmatch('Solid[1-9][0-9]*' if self.options['dimension']==3 else 'Face[1-9][0-9]*',name):
                for tag in items:
                    if tag in owner:reject('cad_region_mapping')
                    owner[tag]=name
        if set(owner)!=set(tags):reject('cad_region_mapping')
        facets=[];assigned=set()
        for face in descriptor['faces']:
            for tag in groups.get(face['ref'],[]):
                if tag in assigned:reject('cad_boundary_mapping')
                assigned.add(tag);facets.append(dict(tag=tag,nodes=list(mesh.getElementNodes(tag)),cad_face_id=face['id']))
        if assigned!=set(mesh.Faces):reject('cad_boundary_coverage')
        source=dict(contract_version='1.0.0',geometry=descriptor,profile_sha256=profile_hash(),mesher_version=profile()['version'],
            options=self.options,nodes=[dict(tag=tag,position_m=[float(v)*.001 for v in mesh.Nodes[tag]]) for tag in sorted(mesh.Nodes)],
            cells=[dict(tag=tag,topology='tet4' if self.options['dimension']==3 else 'tri3',nodes=list(mesh.getElementNodes(tag)),
                region=owner[tag]) for tag in sorted(tags)],facets=sorted(facets,key=lambda f:f['tag']))
        return read('cad_mesh',source)
