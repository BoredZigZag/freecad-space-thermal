// SPDX-License-Identifier: MIT OR Apache-2.0
// Strict v2 binding from canonical identities to compiled spatial operators.
void thermal_spatial(thermal::Data& out,const J& value,const Entities& entities,
                     const std::map<std::string,std::size_t>& nodes,const std::map<std::string,std::size_t>& materials,const J& envelope) {
  spatial::Discretization mesh;mesh.mesh_revision=value.at("mesh_revision").str();
  const auto snapshot_model=Parser{out.canonical_snapshot}.parse();
  std::map<std::string,std::map<std::string,double>> mappings;
  for(const auto& map:snapshot_model.at("mappings").arr())
    if(!mappings[map.at("from_id").str()].emplace(map.at("to_id").str(),map.at("weight").num()).second)fail("spatial_mapping");
  const auto bytes=canonical(J(J::O{{"points",value.at("points")},{"cells",value.at("cells")}}));
  if (mesh.mesh_revision!=sha256(std::string("FCST-spatial-mesh-v1\0",21)+bytes)) fail("spatial_mesh_revision");
  std::set<std::string> mesh_ids;
  for(const auto& cell:value.at("cells").arr())mesh_ids.insert(target(entities,cell.at("element_id").str(),"element").at("mesh_id").str());
  if(mesh_ids.size()!=1)fail("spatial_mesh_count");
  const auto& artifact=entities.at(*mesh_ids.begin()).at("artifact");
  const auto assignment=canonical(J(J::O{{"spatial",value},{"material_laws",envelope.at("material_laws")},{"node_storage",envelope.at("node_storage")}}));
  if(artifact.at("sha256").str()!=sha256(assignment) || artifact.at("byte_length").num()!=static_cast<double>(assignment.size()))fail("spatial_mesh_artifact");
  std::map<std::string,std::size_t> points;std::set<std::string> bound;
  for (const auto& p:value.at("points").arr()) {
    if (!points.emplace(p.at("id").str(),mesh.points.size()).second || entities.contains(p.at("id").str())) fail("spatial_identity");
    target(entities,p.at("node_id").str(),"node");
    spatial::Vector position{};for(std::size_t i=0;i<3;++i)position[i]=p.at("position").at(i).num();
    mesh.points.push_back({p.at("id").str(),nodes.at(p.at("node_id").str()),position});
  }
  const std::map<std::string,std::string> topology{{"tri3","triangle"},{"quad4","quadrilateral"},{"tet4","tetrahedron"},{"hex8","hexahedron"}};
  for (const auto& e:value.at("cells").arr()) {
    const auto id=e.at("element_id").str();const auto& element=target(entities,id,"element");
    if (!bound.insert(id).second) fail("duplicate_id");
    if (element.at("topology").str()!=topology.at(e.at("topology").str())) throw thermal::Error("unsupported_element",id);
    spatial::Cell cell{id,e.at("topology").str(),materials.at(element.at("material_id").str()),{},e.at("thickness_m").num()};
    for (const auto& p:e.at("point_ids").arr()) {if(!points.contains(p.str()))fail("spatial_reference");cell.points.push_back(points.at(p.str()));}
    auto prepared=spatial::prepare(std::move(cell),mesh.points);double volume=0;
    for(const auto& q:prepared.quadrature)volume+=q.volume;
    if(std::abs(volume-element.at("volume").num())>1e-10*std::max(volume,element.at("volume").num()))throw thermal::Error("spatial_volume_mismatch",id);
    std::map<std::string,double> expected;const auto& actual=mappings[id];
    for(const auto& q:prepared.quadrature)for(std::size_t i=0;i<prepared.cell.points.size();++i)
      expected[out.nodes[mesh.points[prepared.cell.points[i]].node].id]+=q.volume*q.shape[i]/volume;
    if(actual.size()!=expected.size())throw thermal::Error("spatial_mapping",id);
    for(const auto& [node,weight]:expected)if(!actual.contains(node) || std::abs(actual.at(node)-weight)>1e-10)throw thermal::Error("spatial_mapping",id);
    mesh.cells.push_back(std::move(prepared));
  }
  if(bound!=std::set<std::string>(out.spatial_element_ids.begin(),out.spatial_element_ids.end()))fail("spatial_unassigned");
  std::map<std::set<std::size_t>,std::size_t> boundary_owners;
  for(const auto& c:mesh.cells) {
    const auto& p=c.cell.points;std::vector<std::vector<std::size_t>> faces;
    if(c.cell.topology=="tri3" || c.cell.topology=="quad4")faces={p};
    else if(c.cell.topology=="tet4")faces={{p[0],p[1],p[2]},{p[0],p[1],p[3]},{p[0],p[2],p[3]},{p[1],p[2],p[3]}};
    else faces={{p[0],p[1],p[2],p[3]},{p[4],p[5],p[6],p[7]},{p[0],p[1],p[5],p[4]},
      {p[1],p[2],p[6],p[5]},{p[2],p[3],p[7],p[6]},{p[3],p[0],p[4],p[7]}};
    for(const auto& f:faces)for(std::size_t i=0;i<f.size();++i)for(std::size_t j=i+1;j<f.size();++j)for(std::size_t k=j+1;k<f.size();++k)
      ++boundary_owners[{f[i],f[j],f[k]}];
  }
  for(const auto& s:value.at("surfaces").arr()) {
    if(entities.contains(s.at("id").str()))fail("spatial_identity");
    spatial::Surface surface{s.at("id").str(),s.at("kind").str(),{},s.at("value_SI").num(),s.at("ambient_K").num()};
    for(const auto& p:s.at("point_ids").arr()){if(!points.contains(p.str()))fail("spatial_reference");surface.points.push_back(points.at(p.str()));}
    // A load selection must be an actual boundary face of a cell, not an arbitrary triangle through the volume.
    std::set<std::size_t> selection(surface.points.begin(),surface.points.end());
    if(!boundary_owners.contains(selection) || boundary_owners.at(selection)!=1)throw thermal::Error("spatial_boundary_selection",surface.id);
    mesh.surfaces.push_back(std::move(surface));
  }
  for(const auto& c:value.at("contacts").arr()) {
    if(entities.contains(c.at("id").str()))fail("spatial_identity");
    spatial::Contact contact{c.at("id").str(),c.at("kind").str(),c.at("calibration_id").str(),{}, {},
      c.at("area_m2").num(),c.at("coefficient_SI").num(),c.at("gap_m").num(),c.at("minimum_temperature_K").num(),
      c.at("maximum_temperature_K").num(),c.at("maximum_power_W").num()};
    for(auto [key,side]:std::initializer_list<std::pair<const char*,std::vector<std::pair<std::size_t,double>>*>>{{"from",&contact.from},{"to",&contact.to}})
      for(const auto& w:c.at(key).arr()){target(entities,w.at("node_id").str(),"node");side->emplace_back(nodes.at(w.at("node_id").str()),w.at("weight").num());}
    mesh.contacts.push_back(std::move(contact));
  }
  // Material bases are local-to-parent. Compose the entire validated frame chain.
  for(auto& m:out.materials)if(m.conductivity_tensor) {
    thermal::Tensor basis{{{1,0,0},{0,1,0},{0,0,1}}};auto id=*m.frame_id;
    for(;;) {
      const auto& f=target(entities,id,"frame");thermal::Tensor next{};
      for(std::size_t i=0;i<3;++i)for(std::size_t j=0;j<3;++j)for(std::size_t k=0;k<3;++k)next[i][j]+=f.at("rotation").at(i).at(k).num()*basis[k][j];
      basis=next;if(!f.has("parent_id"))break;id=f.at("parent_id").str();
    }
    thermal::Tensor global{};for(std::size_t i=0;i<3;++i)for(std::size_t j=0;j<3;++j)for(std::size_t a=0;a<3;++a)for(std::size_t b=0;b<3;++b)
      global[i][j]+=basis[i][a]*(*m.conductivity_tensor)[a][b]*basis[j][b];
    m.conductivity_tensor=global;
    if(value.has("tensor_laws")) {
      const J* table=nullptr;
      for(const auto& law:value.at("tensor_laws").arr())if(law.at("material_id").str()==m.id) {
        if(table)throw thermal::Error("duplicate_id",m.id);table=&law;
      }
      if(table) {
        if(table->at("frame_id").str()!=*m.frame_id)throw thermal::Error("frame",m.id);
        std::vector<double> temperatures;for(const auto& t:table->at("temperatures_K").arr())temperatures.push_back(t.num());
        std::vector<thermal::Tensor> tensors;
        for(const auto& raw:table->at("tensors_W_per_mK").arr()) {
          thermal::Tensor rotated{};
          // Validate the original tensor independently, then rotate both its value and derivative basis.
          thermal::Tensor local{};for(std::size_t i=0;i<3;++i)for(std::size_t j=0;j<3;++j)local[i][j]=raw.at(i).at(j).num();
          (void)thermal::Material(m.id,m.density,m.specific_heat,m.conductivity,local,m.frame_id);
          for(std::size_t i=0;i<3;++i)for(std::size_t j=0;j<3;++j)for(std::size_t a=0;a<3;++a)for(std::size_t b=0;b<3;++b)
            rotated[i][j]+=basis[i][a]*local[a][b]*basis[j][b];
          tensors.push_back(rotated);
        }
        m.tensor_law.emplace(std::move(temperatures),std::move(tensors),table->at("extrapolation").str()=="error"?thermal::Extrapolation::error:thermal::Extrapolation::clamp,
          m.conductivity.minimum_temperature(),m.conductivity.maximum_temperature());
        const auto reference=m.tensor_law->sample(table->at("reference_temperature_K").num()).value;
        for(std::size_t i=0;i<3;++i)for(std::size_t j=0;j<3;++j)
          if(std::abs(reference[i][j]-global[i][j])>1e-10*std::max({1.0,std::abs(reference[i][j]),std::abs(global[i][j])}))throw thermal::Error("spatial_tensor_reference",m.id);
      }
    }
  }
  if(value.has("tensor_laws"))for(const auto& law:value.at("tensor_laws").arr()) {
    auto id=law.at("material_id").str();if(!materials.contains(id) || !out.materials[materials.at(id)].tensor_law)throw thermal::Error("spatial_tensor_reference",id);
  }
  spatial::attach(out,std::move(mesh));
}
