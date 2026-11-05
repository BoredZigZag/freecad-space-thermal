// SPDX-License-Identifier: MIT OR Apache-2.0
#include "fcst/fluid.hpp"
#include "fcst/thermal.hpp"
#include <cmath>
#include <numeric>

namespace fcst::fluid {
namespace {
using thermal::Error;
bool positive(double value) { return std::isfinite(value) && value>0; }
double friction_length(double inlet, double at, double stagnation, double gas_to_cp) {
  const double relative_change=(at-inlet)/at;
  // Write the difference of inverse squares in terms of the relative velocity change.
  return stagnation*relative_change*(2-relative_change)/(2*inlet*inlet)
         -(1-gas_to_cp/2)*std::log1p((at-inlet)/inlet);
}
}

std::vector<Station> solve_duct(const Duct& d, std::span<const double> positions) {
  for (double value:{d.length,d.area,d.hydraulic_diameter,d.outlet_pressure,d.inlet_temperature,d.gas_constant})
    if (!positive(value)) throw Error("fluid_duct_input");
  if (!std::isfinite(d.mass_flow) || d.mass_flow<0 || !std::isfinite(d.darcy_friction_factor) ||
      d.darcy_friction_factor<0 || !std::isfinite(d.gamma) || d.gamma<=1 || d.gamma>2)
    throw Error("fluid_duct_input");
  if (positions.empty() || positions.size()>4096) throw Error("fluid_station");
  for (double x:positions)
    if (!std::isfinite(x) || x<0 || x>d.length) throw Error("fluid_station");

  const double gas_to_cp=(d.gamma-1)/d.gamma;
  const double rt=d.gas_constant*d.inlet_temperature;
  const double speed_scale=std::sqrt(rt);
  const double thermal_enthalpy=rt/gas_to_cp;
  const double static_density=d.outlet_pressure/rt;
  if (!positive(thermal_enthalpy) || !positive(static_density)) throw Error("fluid_range");
  if (d.mass_flow==0)
    return std::vector<Station>(positions.size(),{d.outlet_pressure,d.inlet_temperature,0,static_density,thermal_enthalpy});

  const double boundary_velocity=(d.mass_flow/d.area)*speed_scale/d.outlet_pressure;
  const double friction=d.darcy_friction_factor*(d.length/d.hydraulic_diameter)/2;
  if (!std::isfinite(friction) || friction>1e8 || !positive(boundary_velocity) || boundary_velocity<1e-9)
    throw Error("fluid_range");
  if (boundary_velocity>=std::sqrt(d.gamma)) throw Error("fluid_subsonic_domain");
  const auto stagnation=[&](double speed) { return 1+gas_to_cp*speed*speed/2; };
  const auto outlet=[&](double inlet) {
    const double a=stagnation(inlet);
    return 2*a*boundary_velocity/(1+std::sqrt(1+2*gas_to_cp*a*boundary_velocity*boundary_velocity));
  };

  // Velocities are nondimensionalized by sqrt(R*T_in). The frictionless velocity
  // is an upper bound on the inlet velocity of a subsonic duct with losses.
  double inlet=boundary_velocity, exit=boundary_velocity;
  if (friction>0) {
    double low=0, high=boundary_velocity;
    for (int i=0; i<80; ++i) {
      const double mid=std::midpoint(low,high);
      if (friction_length(mid,outlet(mid),stagnation(mid),gas_to_cp)>friction) low=mid;
      else high=mid;
    }
    inlet=std::midpoint(low,high);
    exit=outlet(inlet);
  }
  const double a=stagnation(inlet);
  std::vector<Station> result;
  result.reserve(positions.size());
  for (double x:positions) {
    double speed=inlet;
    if (x==d.length) speed=exit;
    else if (x>0 && friction>0) {
      const double target=friction*(x/d.length);
      double low=inlet, high=exit;
      for (int i=0; i<80; ++i) {
        const double mid=std::midpoint(low,high);
        if (friction_length(inlet,mid,a,gas_to_cp)<target) low=mid;
        else high=mid;
      }
      speed=std::midpoint(low,high);
    }
    const double temperature_ratio=1+gas_to_cp*(inlet-speed)*(inlet+speed)/2;
    const double pressure=x==d.length?d.outlet_pressure:d.outlet_pressure*(boundary_velocity/speed)*temperature_ratio;
    const double temperature=d.inlet_temperature*temperature_ratio;
    const double velocity=speed_scale*speed;
    const double density=(pressure/rt)/temperature_ratio;
    const double enthalpy=a*thermal_enthalpy;
    if (!positive(pressure) || !positive(temperature) || !positive(velocity) ||
        !positive(density) || !positive(enthalpy)) throw Error("fluid_range");
    result.push_back({pressure,temperature,velocity,density,enthalpy});
  }
  return result;
}
} // namespace fcst::fluid
