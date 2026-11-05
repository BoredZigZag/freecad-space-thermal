// SPDX-License-Identifier: MIT OR Apache-2.0
#include "fcst/fluid.hpp"
#include "fcst/thermal.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <numeric>

namespace fcst::fluid {
namespace {
using thermal::Error;
struct Equilibrium { double pressure, temperature; std::optional<double> quality; };

bool positive(double value) { return std::isfinite(value) && value>0; }
double latent_slope(const SaturationPoint& p) {
  return (p.vapor_energy-p.liquid_energy)/(p.vapor_volume-p.liquid_volume);
}
void validate(const VesselProperties& properties) {
  if (const auto* gas=std::get_if<IdealGas>(&properties)) {
    if (!positive(gas->gas_constant) || !positive(gas->cv)) throw Error("vessel_properties");
    return;
  }
  const auto& table=std::get<std::vector<SaturationPoint>>(properties);
  if (table.size()<2 || table.size()>256) throw Error("vessel_properties");
  for (std::size_t i=0; i<table.size(); ++i) {
    const auto& p=table[i];
    if (!positive(p.pressure) || !positive(p.temperature) || !positive(p.liquid_volume) ||
        !positive(p.vapor_volume) || p.vapor_volume<=p.liquid_volume || !positive(latent_slope(p)))
      throw Error("vessel_properties");
    if (i==0) continue;
    const auto& a=table[i-1];
    const double first_slope=latent_slope(a), last_slope=latent_slope(p);
    const auto [low,high]=std::minmax(first_slope,last_slope);
    // At fixed mixture volume, dU/dP is linear in quality for each pressure.
    // Bounding its values at x=0 and x=1 makes the flash single-valued.
    if (p.pressure<=a.pressure || p.temperature<=a.temperature ||
        p.liquid_volume<a.liquid_volume || p.vapor_volume>a.vapor_volume ||
        !(p.liquid_energy-a.liquid_energy>high*(p.liquid_volume-a.liquid_volume)) ||
        !(p.vapor_energy-a.vapor_energy>low*(p.vapor_volume-a.vapor_volume)))
      throw Error("vessel_properties");
  }
}

Equilibrium flash(const VesselProperties& properties, double volume, double energy) {
  if (!positive(volume) || !std::isfinite(energy)) throw Error("vessel_state");
  if (const auto* gas=std::get_if<IdealGas>(&properties)) {
    const double temperature=energy/gas->cv;
    const double pressure=gas->gas_constant*temperature/volume;
    if (!positive(pressure) || !positive(temperature)) throw Error("vessel_state");
    return {pressure,temperature,{}};
  }
  const auto& table=std::get<std::vector<SaturationPoint>>(properties);
  if (volume<table.back().liquid_volume || volume>table.back().vapor_volume)
    throw Error("vessel_saturation_domain");
  const auto quality=[&](double vl,double vg) { return (volume-vl)/(vg-vl); };
  const auto energy_at=[&](const SaturationPoint& p) {
    return std::lerp(p.liquid_energy,p.vapor_energy,quality(p.liquid_volume,p.vapor_volume));
  };
  if (energy<energy_at(table.front()) || energy>energy_at(table.back()))
    throw Error("vessel_saturation_domain");
  auto upper=std::lower_bound(table.begin()+1,table.end(),energy,
    [&](const auto& row,double u) { return energy_at(row)<u; });
  if (upper==table.end()) throw Error("vessel_saturation_domain");
  const auto& a=*(upper-1);
  const auto& b=*upper;
  const auto at=[&](double fraction) {
    const double x=quality(std::lerp(a.liquid_volume,b.liquid_volume,fraction),
                           std::lerp(a.vapor_volume,b.vapor_volume,fraction));
    return std::pair{x,std::lerp(std::lerp(a.liquid_energy,b.liquid_energy,fraction),
                                 std::lerp(a.vapor_energy,b.vapor_energy,fraction),x)};
  };
  double low=0, high=1;
  for (int i=0; i<55; ++i) {
    const double mid=std::midpoint(low,high);
    if (at(mid).second<energy) low=mid;
    else high=mid;
  }
  const double f=std::midpoint(low,high);
  return {std::lerp(a.pressure,b.pressure,f),std::lerp(a.temperature,b.temperature,f),at(f).first};
}

using State=std::array<double,5>; // mass, internal energy, wall T, discharged mass and enthalpy
State add_scaled(State state,const State& rate,double step) {
  for (std::size_t i=0; i<state.size(); ++i) state[i]+=step*rate[i];
  return state;
}
}

std::vector<VesselSample> solve_vessel(const Vessel& vessel, const VesselProperties& properties,
                                       std::span<const VesselInterval> schedule) {
  validate(properties);
  for (double x:{vessel.volume,vessel.initial_mass,vessel.initial_wall_temperature,vessel.wall_capacity,vessel.maximum_step})
    if (!positive(x)) throw Error("vessel_input");
  if (!std::isfinite(vessel.initial_energy) || !std::isfinite(vessel.wall_conductance) ||
      vessel.wall_conductance<0 || schedule.empty() || schedule.size()>4096)
    throw Error("vessel_input");

  State state{vessel.initial_mass,vessel.initial_energy,vessel.initial_wall_temperature,0,0};
  const auto equilibrium=[&](const State& values) {
    if (!positive(values[0]) || !positive(values[2])) throw Error("vessel_state");
    return flash(properties,vessel.volume/values[0],values[1]/values[0]);
  };
  std::vector<VesselSample> result;
  result.reserve(schedule.size()+1);
  double time=0, fed_mass=0, fed_energy=0;
  const auto record=[&]() {
    const auto eq=equilibrium(state);
    const double mass_defect=(state[0]-vessel.initial_mass)+state[3]-fed_mass;
    const double energy_defect=(state[1]-vessel.initial_energy)+
      vessel.wall_capacity*(state[2]-vessel.initial_wall_temperature)+state[4]-fed_energy;
    for (double x:{state[3],state[4],mass_defect,energy_defect})
      if (!std::isfinite(x)) throw Error("vessel_state");
    result.push_back({time,state[0],state[1],state[2],eq.pressure,eq.temperature,eq.quality,
                      state[3],state[4],mass_defect,energy_defect});
  };
  record();
  std::size_t remaining_steps=100000;
  for (const auto& interval:schedule) {
    if (!positive(interval.duration) || !std::isfinite(interval.inlet_enthalpy) || !std::isfinite(interval.wall_power))
      throw Error("vessel_schedule");
    for (double value:{interval.inlet_mass_flow,interval.outlet_pressure,interval.outlet_conductance})
      if (!std::isfinite(value) || value<0) throw Error("vessel_schedule");
    const double count=std::max(1.0,std::ceil(interval.duration/vessel.maximum_step));
    if (count>static_cast<double>(remaining_steps)) throw Error("vessel_step_limit");
    const auto steps=static_cast<std::size_t>(count);
    remaining_steps-=steps;
    const double dt=interval.duration/count;
    const auto rate=[&](const State& y) {
      const auto eq=equilibrium(y);
      const double out=interval.outlet_conductance*std::max(0.0,eq.pressure-interval.outlet_pressure);
      const double out_energy=out*(y[1]/y[0]+eq.pressure*(vessel.volume/y[0]));
      const double heat=vessel.wall_conductance*(y[2]-eq.temperature);
      return State{interval.inlet_mass_flow-out,interval.inlet_mass_flow*interval.inlet_enthalpy-out_energy+heat,
                   (interval.wall_power-heat)/vessel.wall_capacity,out,out_energy};
    };
    for (std::size_t step=0; step<steps; ++step) {
      const auto k1=rate(state), k2=rate(add_scaled(state,k1,dt/2));
      const auto k3=rate(add_scaled(state,k2,dt/2)), k4=rate(add_scaled(state,k3,dt));
      for (std::size_t i=0; i<state.size(); ++i)
        state[i]+=dt*(k1[i]+2*k2[i]+2*k3[i]+k4[i])/6;
    }
    if (!positive(time+interval.duration) || time+interval.duration<=time) throw Error("vessel_schedule");
    time+=interval.duration;
    fed_mass+=interval.duration*interval.inlet_mass_flow;
    fed_energy+=interval.duration*(interval.wall_power+interval.inlet_mass_flow*interval.inlet_enthalpy);
    record();
  }
  return result;
}
} // namespace fcst::fluid
