# SPDX-License-Identifier: LGPL-2.1-or-later
"""FEM contours of solved spatial temperatures, preserving native field locations."""
from fcst_app.fem_adapter import assert_thread,capability
from fcst_app.discretization import read_input
from fcst_app.persistence import reject,semantic_hash
from .review import colour


class NativeMeshView:
    def __init__(self,session,value):
        assert_thread()
        import Fem
        import ObjectsFem
        self.session=session;self.value=read_input(value)
        if semantic_hash(self.value['model'])!=semantic_hash(session.store.snapshot()):reject('stale_spatial_input')
        points=self.value['spatial']['points'];indices={p['id']:i+1 for i,p in enumerate(points)}
        with session.projection():
            self.mesh=capability(ObjectsFem,'makeMeshResult')(session.doc,'FCSTConductionMesh')
            mesh=Fem.FemMesh()
            for i,p in enumerate(points,1):mesh.addNode(*(v*1000 for v in p['position']),i)
            for i,c in enumerate(self.value['spatial']['cells'],1):
                ids=[indices[p] for p in c['point_ids']]
                if c['topology'] in ('tet4','hex8'):mesh.addVolume(ids,i)
                else:mesh.addFace(ids,i)
            self.mesh.FemMesh=mesh
            self.result=capability(ObjectsFem,'makeResultMechanical')(session.doc,'FCSTConductionResult')
            self.result.Mesh=self.mesh;self.result.NodeNumbers=list(range(1,len(points)+1))
            self.mesh.addProperty('App::PropertyString','FCSTMeshRevision','FCST');self.mesh.FCSTMeshRevision=self.value['spatial']['mesh_revision']
            self.result.addProperty('App::PropertyString','FCSTFieldLocation','FCST');self.result.FCSTFieldLocation='temperature=thermal_node;heat_flux=element_volume_average;frame=global'
            session.root.addObject(self.mesh);session.root.addObject(self.result);self.mesh.ViewObject.Visibility=False

    def show(self,result,sample):
        assert_thread()
        if (self.session.diverged or self.session.check_bindings()
                or semantic_hash(self.value['model'])!=semantic_hash(self.session.store.snapshot())):
            self.hide();reject('stale_result')
        if not 0<=sample<len(result['samples']):reject('result_selection')
        points=self.value['spatial']['points'];node_index={id_:i for i,id_ in enumerate(result['node_ids'])}
        all_values=[row['temperature_K'][node_index[p['node_id']]] for row in result['samples'] for p in points]
        lo,hi=min(all_values),max(all_values)
        temperatures=[result['samples'][sample]['temperature_K'][node_index[p['node_id']]] for p in points]
        with self.session.projection():
            self.result.Temperature=temperatures
            self.mesh.ViewObject.DisplayMode='Faces';self.mesh.ViewObject.ColorMode='ByNode'
            self.mesh.ViewObject.NodeColor={i:colour(t,lo,hi) for i,t in enumerate(temperatures,1)}
            self.mesh.ViewObject.Visibility=True;self.session.doc.recompute()
        return temperatures

    def hide(self):
        with self.session.projection():
            try:self.mesh.ViewObject.Visibility=False
            except (ReferenceError,RuntimeError):pass
