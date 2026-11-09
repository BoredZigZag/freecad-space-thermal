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
fluid::HeatPipe read_heat_pipe(const J& request) {
  return {request.at("length_m").num(),request.at("evaporator_length_m").num(),request.at("condenser_length_m").num(),
    request.at("evaporator_elevation_m").num(),request.at("capillary_head_Pa").num(),request.at("liquid_density_kg_m3").num(),
    request.at("gravity_m_s2").num(),request.at("liquid_loss_Pa_W_m").num(),request.at("vapor_loss_Pa_W_m").num()};
}
fluid::Vessel read_vessel(const J& request,double step) {
  return {request.at("volume_m3").num(),request.at("initial_mass_kg").num(),
    request.at("initial_internal_energy_J").num(),request.at("initial_wall_temperature_K").num(),
    request.at("wall_capacity_J_K").num(),request.at("wall_conductance_W_K").num(),step};
}
fluid::VesselProperties read_vessel_properties(const J& props) {
  const auto& kind=props.at("kind").str();
  if (kind=="ideal_gas") {
    execution_keys(props,{"kind","gas_constant_J_kg_K","cv_J_kg_K"});
    return fluid::IdealGas{props.at("gas_constant_J_kg_K").num(),props.at("cv_J_kg_K").num()};
  }
  if (kind=="volume_energy_table") {
    execution_keys(props,{"kind","volumes_m3_kg","energies_J_kg","points"});
    fluid::VolumeEnergyTable grid{execution_numbers(props.at("volumes_m3_kg")),
                                  execution_numbers(props.at("energies_J_kg")),{}};
    for (const auto& p:props.at("points").arr()) {
      execution_keys(p,{"pressure_Pa","temperature_K","phase_coordinate"});
      grid.points.push_back({p.at("pressure_Pa").num(),p.at("temperature_K").num(),p.at("phase_coordinate").num()});
    }
    return grid;
  }
  if (kind!="saturation_table") fail("vessel_properties");
  execution_keys(props,{"kind","points"});
  std::vector<fluid::SaturationPoint> rows;
  for (const auto& p:props.at("points").arr()) {
    execution_keys(p,{"pressure_Pa","temperature_K","liquid_volume_m3_kg","vapor_volume_m3_kg",
      "liquid_energy_J_kg","vapor_energy_J_kg"});
    rows.push_back({p.at("pressure_Pa").num(),p.at("temperature_K").num(),p.at("liquid_volume_m3_kg").num(),
      p.at("vapor_volume_m3_kg").num(),p.at("liquid_energy_J_kg").num(),p.at("vapor_energy_J_kg").num()});
  }
  return rows;
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
    const auto pipe=read_heat_pipe(request);
    const auto result=capillary_balance(pipe,request.at("heat_load_W").num());
    return J::O{{"effective_length_m",J(result.effective_length)},{"hydrostatic_head_Pa",J(result.hydrostatic_head)},
      {"liquid_loss_Pa",J(result.liquid_loss)},{"vapor_loss_Pa",J(result.vapor_loss)},{"margin_Pa",J(result.margin)},
      {"power_limit_W",J(result.power_limit)},{"capillary_supported",J(result.supported)}};
  });
}

std::string fluid::inspect_grooved_heat_pipe(std::string_view input) {
  return fluid_request(input,[](const J& r) {
    execution_keys(r,{"schema_version","length_m","evaporator_length_m","condenser_length_m",
      "evaporator_end_rise_m","vapor_core_diameter_m","groove_count","groove_width_m","groove_depth_m",
      "contact_angle_deg","gravity_m_s2","fluid_charge_kg","liquid_density_kg_m3","vapor_density_kg_m3",
      "liquid_viscosity_Pa_s","vapor_viscosity_Pa_s","surface_tension_N_m","latent_heat_J_kg"},
      {"liquid_flow_factor","steps_per_section"});
    const auto bounded_integer=[](double value,double minimum,double maximum) {
      if (value<minimum || value>maximum || std::floor(value)!=value) fail("grooved_heat_pipe_input");
      return static_cast<std::size_t>(value);
    };
    const GroovedHeatPipe pipe{r.at("length_m").num(),r.at("evaporator_length_m").num(),r.at("condenser_length_m").num(),
      r.at("evaporator_end_rise_m").num(),r.at("vapor_core_diameter_m").num(),bounded_integer(r.at("groove_count").num(),1,256),
      r.at("groove_width_m").num(),r.at("groove_depth_m").num(),r.at("contact_angle_deg").num(),r.at("gravity_m_s2").num(),
      r.at("fluid_charge_kg").num(),r.at("liquid_density_kg_m3").num(),r.at("vapor_density_kg_m3").num(),
      r.at("liquid_viscosity_Pa_s").num(),r.at("vapor_viscosity_Pa_s").num(),r.at("surface_tension_N_m").num(),
      r.at("latent_heat_J_kg").num(),r.has("liquid_flow_factor")?r.at("liquid_flow_factor").num():1,
      r.has("steps_per_section")?bounded_integer(r.at("steps_per_section").num(),16,256):64};
    const auto result=grooved_heat_pipe_limit(pipe);
    return J::O{{"power_limit_W",J(result.power)},{"minimum_charge_kg",J(result.minimum_charge)},
      {"charge_residual_kg",J(result.charge_residual)},{"pool_mass_kg",J(result.pool_mass)},
      {"maximum_vapor_reynolds",J(result.maximum_vapor_reynolds)}};
  });
}

std::string fluid::inspect_vessel(std::string_view input) {
  return fluid_request(input,[](const J& request) {
    execution_keys(request,{"schema_version","volume_m3","initial_mass_kg","initial_internal_energy_J",
      "initial_wall_temperature_K","wall_capacity_J_K","wall_conductance_W_K","maximum_step_s","properties","schedule"});
    const auto vessel=read_vessel(request,request.at("maximum_step_s").num());
    const auto properties=read_vessel_properties(request.at("properties"));
    std::vector<VesselInterval> schedule;
    for (const auto& s:request.at("schedule").arr()) {
      execution_keys(s,{"duration_s","inlet_mass_flow_kg_s","inlet_enthalpy_J_kg","outlet_pressure_Pa",
        "outlet_conductance_kg_s_Pa","wall_power_W"});
      schedule.push_back({s.at("duration_s").num(),s.at("inlet_mass_flow_kg_s").num(),s.at("inlet_enthalpy_J_kg").num(),
        s.at("outlet_pressure_Pa").num(),s.at("outlet_conductance_kg_s_Pa").num(),s.at("wall_power_W").num()});
    }
    const auto result=solve_vessel(vessel,properties,schedule);
    J::A samples;
    for (const auto& s:result) samples.emplace_back(J::O{{"time_s",J(s.time)},{"mass_kg",J(s.mass)},{"internal_energy_J",J(s.energy)},
      {"wall_temperature_K",J(s.wall_temperature)},{"pressure_Pa",J(s.pressure)},{"temperature_K",J(s.temperature)},
      {"quality",s.quality?J(*s.quality):J()},{"discharged_mass_kg",J(s.mass_discharged)},{"discharged_energy_J",J(s.energy_discharged)},
      {"mass_defect_kg",J(s.mass_defect)},{"energy_defect_J",J(s.energy_defect)}});
    return J::O{{"samples",J(std::move(samples))}};
  });
}

std::string fluid::inspect_vessel_network(std::string_view input) {
  return fluid_request(input,[](const J& request) {
    execution_keys(request,{"schema_version","maximum_step_s","properties","vessels","links","schedule"});
    const auto step=request.at("maximum_step_s").num();
    const auto properties=read_vessel_properties(request.at("properties"));
    std::vector<Vessel> vessels;
    for (const auto& node:request.at("vessels").arr()) {
      execution_keys(node,{"volume_m3","initial_mass_kg","initial_internal_energy_J",
        "initial_wall_temperature_K","wall_capacity_J_K","wall_conductance_W_K"});
      vessels.push_back(read_vessel(node,step));
    }
    std::vector<VesselLink> links;
    for (const auto& link:request.at("links").arr()) {
      execution_keys(link,{"from","to","conductance_kg_s_Pa"},{"inertance_Pa_s2_kg","initial_flow_kg_s"});
      links.push_back({execution_count(link.at("from")),execution_count(link.at("to")),link.at("conductance_kg_s_Pa").num(),
        link.has("inertance_Pa_s2_kg")?link.at("inertance_Pa_s2_kg").num():0,
        link.has("initial_flow_kg_s")?link.at("initial_flow_kg_s").num():0});
    }
    std::vector<VesselNetworkInterval> schedule;
    for (const auto& interval:request.at("schedule").arr()) {
      execution_keys(interval,{"duration_s","wall_power_W","opening"});
      schedule.push_back({interval.at("duration_s").num(),execution_numbers(interval.at("wall_power_W")),
                          execution_numbers(interval.at("opening"))});
    }
    auto result=solve_vessel_network(vessels,properties,links,schedule);
    J::A samples;
    for (const auto& row:result) {
      J::A nodes,flows;
      for (const auto& n:row.nodes) {
        J::O node{{"mass_kg",J(n.mass)},{"internal_energy_J",J(n.energy)},
          {"wall_temperature_K",J(n.wall_temperature)},{"pressure_Pa",J(n.pressure)},{"temperature_K",J(n.temperature)},
          {"quality",n.quality?J(*n.quality):J()}};
        if (std::holds_alternative<VolumeEnergyTable>(properties)) {
          const char* phase=n.phase==Phase::liquid?"liquid":n.phase==Phase::vapor?"vapor":"saturated";
          node.emplace("phase",J(phase));
        }
        nodes.emplace_back(std::move(node));
      }
      for (double flow:row.link_flow) flows.emplace_back(flow);
      samples.emplace_back(J::O{{"time_s",J(row.time)},{"mass_defect_kg",J(row.mass_defect)},
        {"energy_defect_J",J(row.energy_defect)},{"vessels",J(std::move(nodes))},{"link_flow_kg_s",J(std::move(flows))}});
    }
    return J::O{{"samples",J(std::move(samples))}};
  });
}

std::string fluid::inspect_heat_pipe_transient(std::string_view input) {
  return fluid_request(input,[](const J& request) {
    execution_keys(request,{"schema_version","hydraulics","condenser_temperature_K","initial_temperature_K","startup_temperature_K",
      "evaporator_capacity_J_K","passive_conductance_W_K","latent_conductance_W_K","latent_heat_J_kg","fluid_mass_kg",
      "initial_wick_mass_kg","reprime_mass_kg","refill_rate_kg_s","schedule"});
    const auto& h=request.at("hydraulics");
    execution_keys(h,{"length_m","evaporator_length_m","condenser_length_m","evaporator_elevation_m","capillary_head_Pa",
      "liquid_density_kg_m3","gravity_m_s2","liquid_loss_Pa_W_m","vapor_loss_Pa_W_m"});
    const HeatPipeTransient pipe{read_heat_pipe(h),request.at("condenser_temperature_K").num(),request.at("initial_temperature_K").num(),
      request.at("startup_temperature_K").num(),request.at("evaporator_capacity_J_K").num(),request.at("passive_conductance_W_K").num(),
      request.at("latent_conductance_W_K").num(),request.at("latent_heat_J_kg").num(),request.at("fluid_mass_kg").num(),
      request.at("initial_wick_mass_kg").num(),request.at("reprime_mass_kg").num(),request.at("refill_rate_kg_s").num()};
    std::vector<HeatPipeInterval> schedule;
    for (const auto& s:request.at("schedule").arr()) {
      execution_keys(s,{"duration_s","heat_load_W"});
      schedule.push_back({s.at("duration_s").num(),s.at("heat_load_W").num()});
    }
    const auto result=solve_heat_pipe(pipe,schedule);
    const auto rows=[](const auto& samples) {
      J::A out;
      for (const auto& s:samples) {
        const char* mode=s.mode==HeatPipeMode::priming?"priming":s.mode==HeatPipeMode::active?"active":"dry";
        out.emplace_back(J::O{{"time_s",J(s.time)},{"temperature_K",J(s.temperature)},{"wick_mass_kg",J(s.wick_mass)},
          {"reservoir_mass_kg",J(s.reservoir_mass)},{"rejected_energy_J",J(s.rejected_energy)},{"energy_defect_J",J(s.energy_defect)},
          {"mode",J(mode)}});
      }
      return out;
    };
    return J::O{{"samples",J(rows(result.samples))},{"events",J(rows(result.events))},{"capillary_limit_W",J(result.capillary_limit)}};
  });
}
