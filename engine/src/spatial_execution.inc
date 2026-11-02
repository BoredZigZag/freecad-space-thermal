// SPDX-License-Identifier: MIT OR Apache-2.0
std::string spatial::inspect(std::string_view input) {
  try {
    auto j=Parser{input}.parse();execution_keys(j,{"thermal_input","temperature_K"});
    auto model=thermal::load(dump(j.at("thermal_input")));const auto& d=model.data();
    if(!d.spatial)fail("spatial_required");
    auto t=execution_numbers(j.at("temperature_K"));if(t.size()!=d.nodes.size())fail("dimension");
    thermal::Assembly assembly(model);auto x=assembly.initial_temperature();
    J::A ids,capacity,storage;
    for(std::size_t i=0;i<d.nodes.size();++i) {
      const auto& n=d.nodes[i];if(n.equation)x[*n.equation]=t[i];else if(t[i]!=n.temperature)fail("boundary");
      ids.emplace_back(n.id);capacity.emplace_back(model.storage_capacity(i,t[i]));storage.emplace_back(model.storage_change(i,n.temperature,t[i]));
    }
    auto value=spatial::evaluate(*d.spatial,d,t,true);auto result=assembly.steady_linearize(0,x);
    J::A flux,jacobian;
    for(std::size_t i=0;i<d.spatial->cells.size();++i)flux.emplace_back(J::O{{"element_id",J(d.spatial->cells[i].cell.id)},{"heat_flux_W_per_m2",numbers(value.cell_flux[i])}});
    const auto& pattern=*assembly.sparsity();
    for(std::size_t i=0;i<pattern.dimension();++i)for(auto k=pattern.offsets()[i];k<pattern.offsets()[i+1];++k)
      jacobian.emplace_back(J::A{J(static_cast<double>(i)),J(static_cast<double>(pattern.columns()[k])),J(result.d_temperature.values()[k])});
    return dump(J(J::O{{"status",J("passed")},{"model_hash",J(d.model_hash)},{"preparation_hash",J(d.preparation_hash)},
      {"execution_mode",J("fcst_native")},{"mesh_revision",J(d.spatial->mesh_revision)},
      {"node_ids",J(ids)},{"capacity_J_per_K",J(capacity)},{"storage_change_J",J(storage)},
      {"conductive_in_W",numbers(result.balance.conductive_in)},{"load_in_W",numbers(result.balance.load_in)},
      {"environment_in_W",numbers(result.balance.environment_in)},{"residual_W",numbers(result.balance.residual)},
      {"jacobian",J(jacobian)},{"cells",J(flux)},{"flux_location",J("element_volume_average")},{"flux_frame",J("global")},
      {"source_revision",J(thermal::thermal_backend_capabilities().source_revision)}}));
  } catch(const thermal::Error& e) {
    J::O out{{"status",J("failed")},{"code",J(e.code)}};if(!e.entity_id.empty())out.emplace("entity_id",J(e.entity_id));
    return dump(J(out));
  } catch(const Error& e) {return dump(J(J::O{{"status",J("failed")},{"code",J(e.code)}}));}
    catch(...) {return "{\"status\":\"failed\",\"code\":\"unavailable\"}";}
}
