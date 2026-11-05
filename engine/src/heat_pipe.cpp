// SPDX-License-Identifier: MIT OR Apache-2.0
#include "fcst/fluid.hpp"
#include "fcst/thermal.hpp"
#include <algorithm>
#include <cmath>
#include <numeric>

namespace fcst::fluid {
namespace {
using thermal::Error;
struct Trajectory { double temperature_rise, integral; };

Trajectory evolve(double rise, double heating, double conductance, double capacity, double time) {
  const double z=(conductance/capacity)*time;
  if (!std::isfinite(z)) throw Error("heat_pipe_transient_range");
  const double phi=z==0?1:-std::expm1(-z)/z;
  // The two integrals of exp(-z) need their limits near z=0.
  const double psi=z<1e-4?.5-z/6+z*z/24:(1-phi)/z;
  const double heat_rise=(heating/capacity)*time;
  const double next=rise*std::exp(-z)+heat_rise*phi;
  const double integral=(rise*phi+heat_rise*psi)*time;
  if (!std::isfinite(next) || !std::isfinite(integral)) throw Error("heat_pipe_transient_range");
  return {next,integral};
}

template<class Crossed> double crossing(double high, Crossed crossed) {
  double low=0;
  for (int i=0; i<55; ++i) {
    const double mid=std::midpoint(low,high);
    if (crossed(mid)) high=mid;
    else low=mid;
  }
  return high;
}
}

HeatPipeRun solve_heat_pipe(const HeatPipeTransient& pipe, std::span<const HeatPipeInterval> schedule) {
  for (double x:{pipe.condenser_temperature,pipe.evaporator_capacity,pipe.latent_conductance,
                pipe.latent_heat,pipe.fluid_mass,pipe.reprime_mass})
    if (!std::isfinite(x) || x<=0) throw Error("heat_pipe_transient_input");
  for (double x:{pipe.initial_temperature,pipe.startup_temperature,pipe.passive_conductance,pipe.initial_wick_mass,pipe.refill_rate})
    if (!std::isfinite(x) || x<0) throw Error("heat_pipe_transient_input");
  if (pipe.initial_temperature<pipe.condenser_temperature || pipe.startup_temperature<pipe.condenser_temperature ||
      pipe.reprime_mass>pipe.fluid_mass || pipe.initial_wick_mass>pipe.fluid_mass || schedule.empty() || schedule.size()>4096)
    throw Error("heat_pipe_transient_input");
  const double limit=capillary_balance(pipe.hydraulics,0).power_limit;
  const double refill=std::min(pipe.refill_rate,limit/pipe.latent_heat);
  const double initial_rise=pipe.initial_temperature-pipe.condenser_temperature;
  const double startup_rise=pipe.startup_temperature-pipe.condenser_temperature;
  double rise=initial_rise, inventory=pipe.initial_wick_mass, time=0, rejected=0, energy_input=0;
  auto mode=inventory<pipe.reprime_mass?HeatPipeMode::dry:HeatPipeMode::priming;
  if (mode==HeatPipeMode::priming && rise>=startup_rise) mode=HeatPipeMode::active;
  HeatPipeRun run{{},{},limit};
  const auto sample=[&] {
    const double temperature=pipe.condenser_temperature+rise;
    const double defect=pipe.evaporator_capacity*(rise-initial_rise)+rejected-energy_input;
    for (double x:{temperature,inventory,rejected,defect,time})
      if (!std::isfinite(x)) throw Error("heat_pipe_transient_range");
    return HeatPipeSample{time,temperature,inventory,pipe.fluid_mass-inventory,rejected,defect,mode};
  };
  run.samples.push_back(sample());
  for (const auto& interval:schedule) {
    if (!std::isfinite(interval.duration) || interval.duration<=0 ||
        !std::isfinite(interval.heat_load) || interval.heat_load<0 ||
        !std::isfinite(time+interval.duration) || time+interval.duration<=time)
      throw Error("heat_pipe_schedule");
    const double end=time+interval.duration;
    while (time<end) {
      const double duration=end-time;
      const double conductance=pipe.passive_conductance+(mode==HeatPipeMode::active?pipe.latent_conductance:0);
      const auto trajectory=[&](double t) { return evolve(rise,interval.heat_load,conductance,pipe.evaporator_capacity,t); };
      double step=duration, mass_change=0;
      auto next_mode=mode;
      if (mode==HeatPipeMode::priming && (rise>=startup_rise || trajectory(duration).temperature_rise>=startup_rise)) {
        step=rise>=startup_rise?0:crossing(duration,[&](double t) { return trajectory(t).temperature_rise>=startup_rise; });
        next_mode=HeatPipeMode::active;
      } else if (mode==HeatPipeMode::dry) {
        if (refill>0 && (pipe.reprime_mass-inventory)/refill<=duration) {
          step=(pipe.reprime_mass-inventory)/refill;
          next_mode=HeatPipeMode::priming;
        }
        mass_change=step*refill;
      } else if (mode==HeatPipeMode::active) {
        const double threshold=limit/pipe.latent_conductance;
        const double final_rise=trajectory(duration).temperature_rise;
        if (rise>threshold || final_rise>threshold) {
          double start=0, finish=duration;
          if (rise<=threshold)
            start=crossing(duration,[&](double t) { return trajectory(t).temperature_rise>=threshold; });
          else if (final_rise<threshold)
            finish=crossing(duration,[&](double t) { return trajectory(t).temperature_rise<=threshold; });
          const double start_rise=trajectory(start).temperature_rise;
          const auto depletion=[&](double t) {
            const double elapsed=std::max(0.0,std::min(t,finish)-start);
            const double integral=evolve(start_rise,interval.heat_load,conductance,pipe.evaporator_capacity,elapsed).integral;
            return std::max(0.0,pipe.latent_conductance*integral-limit*elapsed)/pipe.latent_heat;
          };
          if (depletion(finish)>=inventory) {
            step=crossing(finish,[&](double t) { return depletion(t)>=inventory; });
            next_mode=HeatPipeMode::dry;
          }
          mass_change=-depletion(step);
        }
      }
      const auto traveled=trajectory(step);
      rise=traveled.temperature_rise;
      rejected+=conductance*traveled.integral;
      energy_input+=interval.heat_load*step;
      inventory+=mass_change;
      time=step==duration?end:std::min(end,time+step);
      if (next_mode!=mode) {
        if (run.events.size()==4096) throw Error("heat_pipe_event_limit");
        if (next_mode==HeatPipeMode::dry) inventory=0;
        if (next_mode==HeatPipeMode::priming) inventory=pipe.reprime_mass;
        mode=next_mode;
        run.events.push_back(sample());
        if (mode==HeatPipeMode::priming && rise>=startup_rise) {
          if (run.events.size()==4096) throw Error("heat_pipe_event_limit");
          mode=HeatPipeMode::active;
          run.events.push_back(sample());
        }
      }
    }
    run.samples.push_back(sample());
  }
  return run;
}
} // namespace fcst::fluid
