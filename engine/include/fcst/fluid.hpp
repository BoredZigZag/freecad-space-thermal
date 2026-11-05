// SPDX-License-Identifier: MIT OR Apache-2.0
#pragma once
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
} // namespace fcst::fluid
