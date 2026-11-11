// SPDX-License-Identifier: MIT OR Apache-2.0
#pragma once
#include <cstddef>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <variant>
#include <vector>

namespace fcst::fluid {
// Steady, subsonic, adiabatic flow of a calorically perfect gas in a constant-area duct.
struct Duct {
  double length, area, hydraulic_diameter, darcy_friction_factor;
  double mass_flow, outlet_pressure, inlet_temperature, gas_constant, gamma;
};
struct Station {
  double pressure, temperature, velocity, density, stagnation_enthalpy;
};
std::vector<Station> solve_duct(const Duct&, std::span<const double> positions);
std::string inspect_duct(std::string_view);

// Properties at a single prescribed pressure. Outside the saturation dome
// the model uses local constant specific heats and does not predict density.
struct Saturation {
  double pressure, temperature, liquid_enthalpy, vapor_enthalpy, liquid_density, vapor_density;
  double liquid_cp, vapor_cp, minimum_temperature, maximum_temperature;
};
enum class Phase { liquid, saturated, vapor };
struct HeatedState {
  double heat_added, enthalpy, temperature;
  Phase phase;
  std::optional<double> quality, density;
};
std::vector<HeatedState> heated_stream(const Saturation&, double mass_flow, double inlet_enthalpy,
                                        std::span<const double> segment_heat);
std::string inspect_heated_stream(std::string_view);

struct HeatPipe {
  double length, evaporator_length, condenser_length, evaporator_elevation;
  double capillary_head, liquid_density, gravity, liquid_loss_coefficient, vapor_loss_coefficient;
};
struct CapillaryBalance {
  double effective_length, hydrostatic_head, liquid_loss, vapor_loss, margin, power_limit;
  bool supported;
};
CapillaryBalance capillary_balance(const HeatPipe&, double heat_load);
std::string inspect_heat_pipe(std::string_view);

struct GrooveEvaporatorWetting {
  double minimum_wetted_fraction, fully_wet_limit;
};
struct GroovedHeatPipe {
  double length, evaporator_length, condenser_length, end_rise, core_diameter;
  std::size_t groove_count;
  double groove_width, groove_depth, contact_angle_deg, gravity;
  double fluid_charge, liquid_density, vapor_density, liquid_viscosity, vapor_viscosity, surface_tension, latent_heat;
  double liquid_flow_factor=1;
  std::size_t steps_per_section=64;
  std::optional<double> groove_area;
  std::optional<GrooveEvaporatorWetting> evaporator_wetting;
};
struct GroovedHeatPipeLimit {
  double power, minimum_charge, charge_residual, pool_mass, maximum_vapor_reynolds;
  std::optional<double> evaporator_wetted_fraction;
};
GroovedHeatPipeLimit grooved_heat_pipe_limit(const GroovedHeatPipe&);
std::string inspect_grooved_heat_pipe(std::string_view);

struct IdealGas { double gas_constant, cv; };
struct SaturationPoint {
  double pressure, temperature, liquid_volume, vapor_volume, liquid_energy, vapor_energy;
};
struct VolumeEnergyPoint { double pressure, temperature, phase_coordinate; };
struct VolumeEnergyTable {
  std::vector<double> volumes, energies;
  std::vector<VolumeEnergyPoint> points; // volume-major
};
using VesselProperties=std::variant<IdealGas,std::vector<SaturationPoint>,VolumeEnergyTable>;
struct Vessel {
  double volume, initial_mass, initial_energy, initial_wall_temperature, wall_capacity, wall_conductance, maximum_step;
};
struct VesselInterval {
  double duration, inlet_mass_flow, inlet_enthalpy, outlet_pressure, outlet_conductance, wall_power;
};
struct VesselSample {
  double time, mass, energy, wall_temperature, pressure, temperature;
  std::optional<double> quality;
  double mass_discharged, energy_discharged, mass_defect, energy_defect;
};
std::vector<VesselSample> solve_vessel(const Vessel&, const VesselProperties&, std::span<const VesselInterval>);
std::string inspect_vessel(std::string_view);

struct VesselLink { std::size_t from, to; double conductance, inertance=0, initial_flow=0; };
struct VesselNetworkInterval {
  double duration;
  std::vector<double> wall_power, opening;
};
struct VesselNetworkNode {
  double mass, energy, wall_temperature, pressure, temperature;
  std::optional<double> quality;
  std::optional<Phase> phase;
};
struct VesselNetworkSample {
  double time, mass_defect, energy_defect;
  std::vector<VesselNetworkNode> nodes;
  std::vector<double> link_flow;
};
std::vector<VesselNetworkSample> solve_vessel_network(std::span<const Vessel>, const VesselProperties&,
    std::span<const VesselLink>, std::span<const VesselNetworkInterval>);
std::string inspect_vessel_network(std::string_view);

struct HeatPipeTransient {
  HeatPipe hydraulics;
  double condenser_temperature, initial_temperature, startup_temperature, evaporator_capacity;
  double passive_conductance, latent_conductance, latent_heat, fluid_mass, initial_wick_mass, reprime_mass, refill_rate;
};
struct HeatPipeInterval { double duration, heat_load; };
enum class HeatPipeMode { priming, active, dry };
struct HeatPipeSample {
  double time, temperature, wick_mass, reservoir_mass, rejected_energy, energy_defect;
  HeatPipeMode mode;
};
struct HeatPipeRun { std::vector<HeatPipeSample> samples, events; double capillary_limit; };
HeatPipeRun solve_heat_pipe(const HeatPipeTransient&, std::span<const HeatPipeInterval>);
std::string inspect_heat_pipe_transient(std::string_view);
} // namespace fcst::fluid
