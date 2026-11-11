// SPDX-License-Identifier: MIT OR Apache-2.0
#include "fcst/fluid.hpp"
#include "fcst/thermal.hpp"
#include <algorithm>
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

std::vector<HeatedState> heated_stream(const Saturation& s, double mass_flow, double inlet_enthalpy,
                                        std::span<const double> segment_heat) {
  for (double value:{s.pressure,s.temperature,s.liquid_density,s.vapor_density,s.liquid_cp,s.vapor_cp,
                    s.minimum_temperature,s.maximum_temperature,mass_flow})
    if (!positive(value)) throw Error("fluid_heated_input");
  const double latent_heat=s.vapor_enthalpy-s.liquid_enthalpy;
  if (!positive(latent_heat) || !std::isfinite(inlet_enthalpy) || s.liquid_density<=s.vapor_density ||
      s.minimum_temperature>s.temperature || s.maximum_temperature<s.temperature)
    throw Error("fluid_heated_input");
  if (segment_heat.empty() || segment_heat.size()>4096) throw Error("fluid_heated_input");

  auto evaluate=[&](double heat_added) {
    const double h=inlet_enthalpy+heat_added/mass_flow;
    if (!std::isfinite(h)) throw Error("fluid_range");
    HeatedState state{heat_added,h,s.temperature,Phase::saturated,{},{}};
    if (h<s.liquid_enthalpy) {
      state.phase=Phase::liquid;
      state.temperature+=(h-s.liquid_enthalpy)/s.liquid_cp;
    } else if (h>s.vapor_enthalpy) {
      state.phase=Phase::vapor;
      state.temperature+=(h-s.vapor_enthalpy)/s.vapor_cp;
    } else {
      const double x=(h-s.liquid_enthalpy)/latent_heat;
      const double rho=1/std::lerp(1/s.liquid_density,1/s.vapor_density,x);
      if (!positive(rho)) throw Error("fluid_range");
      state.quality=x;
      state.density=rho;
    }
    if (state.temperature<s.minimum_temperature || state.temperature>s.maximum_temperature)
      throw Error("fluid_temperature_domain");
    return state;
  };
  std::vector<HeatedState> result;
  result.reserve(segment_heat.size()+1);
  double heat_added=0;
  result.push_back(evaluate(heat_added));
  for (double heat:segment_heat) {
    heat_added+=heat;
    result.push_back(evaluate(heat_added));
  }
  return result;
}

CapillaryBalance capillary_balance(const HeatPipe& pipe, double heat_load) {
  for (double value:{pipe.length,pipe.evaporator_length,pipe.condenser_length,pipe.capillary_head,pipe.liquid_density})
    if (!positive(value)) throw Error("heat_pipe_input");
  const double active_length=pipe.evaporator_length+pipe.condenser_length;
  if (active_length>pipe.length || !std::isfinite(pipe.evaporator_elevation) ||
      std::abs(pipe.evaporator_elevation)>pipe.length)
    throw Error("heat_pipe_input");
  for (double value:{pipe.gravity,pipe.liquid_loss_coefficient,pipe.vapor_loss_coefficient,heat_load})
    if (!std::isfinite(value) || value<0) throw Error("heat_pipe_input");

  const double effective=pipe.length-active_length/2;
  const double liquid_resistance=effective*pipe.liquid_loss_coefficient;
  const double vapor_resistance=effective*pipe.vapor_loss_coefficient;
  const double resistance=liquid_resistance+vapor_resistance;
  if (!positive(resistance)) throw Error("heat_pipe_resistance");
  const double head=pipe.liquid_density*pipe.gravity*pipe.evaporator_elevation;
  const double liquid_loss=liquid_resistance*heat_load;
  const double vapor_loss=vapor_resistance*heat_load;
  const double available=pipe.capillary_head-head;
  const double limit=std::max(0.0,available)/resistance;
  const double margin=std::fma(-resistance,heat_load,available);
  for (double value:{head,liquid_loss,vapor_loss,limit,margin})
    if (!std::isfinite(value)) throw Error("fluid_range");
  return {effective,head,liquid_loss,vapor_loss,margin,limit,available>=0 && heat_load<=limit};
}
} // namespace fcst::fluid
