// SPDX-License-Identifier: MIT OR Apache-2.0
#pragma once
#include <optional>
#include <span>
#include <string>
#include <string_view>
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
} // namespace fcst::fluid
