// SPDX-License-Identifier: MIT OR Apache-2.0
// Native execution JSON adapter using the shared bounded codec.
namespace {
template<class Evaluate> std::string fluid_request(std::string_view input, Evaluate evaluate) {
  try {
    if (input.size()>1048576) fail("input_limit");
    const auto request=Parser{input}.parse();
    if (!request.has("schema_version")) fail("schema");
    if (request.at("schema_version").num()!=1) fail("version");
    auto result=evaluate(request);
    result.emplace("status",J("passed"));
    result.emplace("schema_version",J(1.0));
    result.emplace("execution_mode",J("fcst_native"));
    result.emplace("source_revision",J(thermal::thermal_backend_capabilities().source_revision));
    result.emplace("input_sha256",J(thermal::thermal_digest(input)));
    return dump(J(std::move(result)));
  } catch (const thermal::Error& e) { return dump(J(J::O{{"status",J("failed")},{"code",J(e.code)}})); }
    catch (const Error& e) { return dump(J(J::O{{"status",J("failed")},{"code",J(e.code)}})); }
    catch (...) { return "{\"status\":\"failed\",\"code\":\"fluid_schema\"}"; }
}
}

std::string fluid::inspect_duct(std::string_view input) {
  return fluid_request(input,[](const J& request) {
    execution_keys(request,{"schema_version","length_m","area_m2","hydraulic_diameter_m","darcy_friction_factor",
      "mass_flow_kg_s","outlet_pressure_Pa","inlet_temperature_K","gas_constant_J_kg_K","gamma","positions_m"});
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
    return J::O{{"mass_flow_kg_s",J(duct.mass_flow)},{"stations",J(stations)}};
  });
}

std::string fluid::inspect_heated_stream(std::string_view input) {
  return fluid_request(input,[](const J& request) {
    execution_keys(request,{"schema_version","saturation","mass_flow_kg_s","inlet_enthalpy_J_kg","segment_heat_W"});
    const auto& v=request.at("saturation");
    execution_keys(v,{"pressure_Pa","temperature_K","liquid_enthalpy_J_kg","vapor_enthalpy_J_kg","liquid_density_kg_m3",
      "vapor_density_kg_m3","liquid_cp_J_kg_K","vapor_cp_J_kg_K","minimum_temperature_K","maximum_temperature_K"});
    const Saturation s{v.at("pressure_Pa").num(),v.at("temperature_K").num(),v.at("liquid_enthalpy_J_kg").num(),
      v.at("vapor_enthalpy_J_kg").num(),v.at("liquid_density_kg_m3").num(),v.at("vapor_density_kg_m3").num(),
      v.at("liquid_cp_J_kg_K").num(),v.at("vapor_cp_J_kg_K").num(),
      v.at("minimum_temperature_K").num(),v.at("maximum_temperature_K").num()};
    const double mass_flow=request.at("mass_flow_kg_s").num();
    const auto heat=execution_numbers(request.at("segment_heat_W"));
    const auto states=heated_stream(s,mass_flow,request.at("inlet_enthalpy_J_kg").num(),heat);
    J::A stations;
    for (const auto& station:states) {
      const char* phase=station.phase==Phase::saturated?"saturated":station.phase==Phase::liquid?"liquid":"vapor";
      stations.emplace_back(J::O{{"heat_added_W",J(station.heat_added)},{"enthalpy_J_kg",J(station.enthalpy)},
        {"temperature_K",J(station.temperature)},{"phase",J(phase)},
        {"quality",station.quality?J(*station.quality):J()},
        {"density_kg_m3",station.density?J(*station.density):J()}});
    }
    return J::O{{"pressure_Pa",J(s.pressure)},{"mass_flow_kg_s",J(mass_flow)},{"stations",J(stations)}};
  });
}

std::string fluid::inspect_heat_pipe(std::string_view input) {
  return fluid_request(input,[](const J& request) {
    execution_keys(request,{"schema_version","length_m","evaporator_length_m","condenser_length_m","evaporator_elevation_m",
      "capillary_head_Pa","liquid_density_kg_m3","gravity_m_s2","liquid_loss_Pa_W_m","vapor_loss_Pa_W_m","heat_load_W"});
    const HeatPipe pipe{request.at("length_m").num(),request.at("evaporator_length_m").num(),request.at("condenser_length_m").num(),
      request.at("evaporator_elevation_m").num(),request.at("capillary_head_Pa").num(),request.at("liquid_density_kg_m3").num(),
      request.at("gravity_m_s2").num(),request.at("liquid_loss_Pa_W_m").num(),request.at("vapor_loss_Pa_W_m").num()};
    const auto result=capillary_balance(pipe,request.at("heat_load_W").num());
    return J::O{{"effective_length_m",J(result.effective_length)},{"hydrostatic_head_Pa",J(result.hydrostatic_head)},
      {"liquid_loss_Pa",J(result.liquid_loss)},{"vapor_loss_Pa",J(result.vapor_loss)},{"margin_Pa",J(result.margin)},
      {"power_limit_W",J(result.power_limit)},{"capillary_supported",J(result.supported)}};
  });
}
