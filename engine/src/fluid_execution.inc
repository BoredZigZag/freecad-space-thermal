// SPDX-License-Identifier: MIT OR Apache-2.0
// Native execution JSON adapter using the shared bounded codec.
std::string fluid::inspect_duct(std::string_view input) {
  try {
    if (input.size()>1048576) fail("input_limit");
    const auto request=Parser{input}.parse();
    execution_keys(request,{"schema_version","length_m","area_m2","hydraulic_diameter_m","darcy_friction_factor",
      "mass_flow_kg_s","outlet_pressure_Pa","inlet_temperature_K","gas_constant_J_kg_K","gamma","positions_m"});
    if (request.at("schema_version").num()!=1) fail("version");
    const Duct duct{request.at("length_m").num(),request.at("area_m2").num(),request.at("hydraulic_diameter_m").num(),
      request.at("darcy_friction_factor").num(),request.at("mass_flow_kg_s").num(),request.at("outlet_pressure_Pa").num(),
      request.at("inlet_temperature_K").num(),request.at("gas_constant_J_kg_K").num(),request.at("gamma").num()};
    const auto positions=execution_numbers(request.at("positions_m"));
    const auto solution=solve_duct(duct,positions);
    J::A stations;
    for (std::size_t i=0; i<positions.size(); ++i) {
      const auto& station=solution[i];
      stations.emplace_back(J::O{{"position_m",J(positions[i])},{"pressure_Pa",J(station.pressure)},
        {"temperature_K",J(station.temperature)},{"velocity_m_s",J(station.velocity)},{"density_kg_m3",J(station.density)},
        {"stagnation_enthalpy_J_kg",J(station.stagnation_enthalpy)}});
    }
    return dump(J(J::O{{"status",J("passed")},{"schema_version",J(1.0)},{"execution_mode",J("fcst_native")},
      {"source_revision",J(thermal::thermal_backend_capabilities().source_revision)},
      {"input_sha256",J(thermal::thermal_digest(input))},{"mass_flow_kg_s",J(duct.mass_flow)},{"stations",J(stations)}}));
  } catch (const thermal::Error& e) { return dump(J(J::O{{"status",J("failed")},{"code",J(e.code)}})); }
    catch (const Error& e) { return dump(J(J::O{{"status",J("failed")},{"code",J(e.code)}})); }
    catch (...) { return "{\"status\":\"failed\",\"code\":\"fluid_schema\"}"; }
}
