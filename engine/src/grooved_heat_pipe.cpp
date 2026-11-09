// SPDX-License-Identifier: MIT OR Apache-2.0
#include "fcst/fluid.hpp"
#include "fcst/thermal.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <numbers>
#include <numeric>
#include <vector>

namespace fcst::fluid {
namespace {
using thermal::Error;
constexpr double pi=std::numbers::pi;

bool positive(double value) { return std::isfinite(value) && value>0; }

// Reflect a full open groove across its shear-free surface and take
// half of the laminar rectangular-duct volume conductance times viscosity.
double full_groove_conductance(double width,double depth) {
  const double short_side=std::min(width,2*depth), long_side=std::max(width,2*depth);
  double sum=0;
  for (int n=1; n<=21; n+=2)
    sum+=std::tanh(n*pi*long_side/(2*short_side))/std::pow(static_cast<double>(n),5);
  return long_side*std::pow(short_side,3)/24*
    (1-192*short_side*sum/(std::pow(pi,5)*long_side));
}

double recessed_area(double width,double sine) {
  if (sine<1e-4) return width*width*sine/6;
  return width*width*(std::asin(sine)-sine*std::sqrt(1-sine*sine))/(4*sine*sine);
}

struct Section {
  double liquid_area, pool_area, resistance, inverse_vapor_diameter;
};

struct Shot {
  double condenser_suction, charge, pool_mass, peak_reynolds;
};

void validate(const GroovedHeatPipe& p) {
  for (double value:{p.length,p.evaporator_length,p.condenser_length,p.core_diameter,p.groove_width,
                     p.groove_depth,p.fluid_charge,p.liquid_density,p.vapor_density,p.liquid_viscosity,
                     p.vapor_viscosity,p.surface_tension,p.latent_heat,p.liquid_flow_factor})
    if (!positive(value)) throw Error("grooved_heat_pipe_input");
  if (!std::isfinite(p.end_rise) || p.end_rise<0 || p.end_rise>p.length/4 ||
      !std::isfinite(p.gravity) || p.gravity<0 || !std::isfinite(p.contact_angle_deg) ||
      p.contact_angle_deg<0 || p.contact_angle_deg>75 || p.liquid_density<=p.vapor_density ||
      p.evaporator_length+p.condenser_length>p.length || p.groove_count<1 || p.groove_count>256 ||
      p.groove_count*p.groove_width>pi*p.core_diameter || p.groove_depth<p.groove_width/2 ||
      p.liquid_flow_factor<.1 || p.liquid_flow_factor>10 || p.steps_per_section<16 || p.steps_per_section>256)
    throw Error("grooved_heat_pipe_input");
}
}

GroovedHeatPipeLimit grooved_heat_pipe_limit(const GroovedHeatPipe& p) {
  validate(p);
  const double density_difference=p.liquid_density-p.vapor_density;
  const double slope=p.end_rise/p.length;
  const double axial_head_gradient=density_difference*p.gravity*slope;
  const double normal_head_gradient=density_difference*p.gravity*std::sqrt(1-slope*slope);
  const double radius=p.core_diameter/2;
  const double groove_area=p.groove_width*p.groove_depth;
  const double core_area=pi*radius*radius;
  const double vapor_fill_mass=p.vapor_density*(core_area+p.groove_count*groove_area)*p.length;
  const double capillary_scale=2*p.surface_tension/p.groove_width;
  const double groove_limit=capillary_scale*std::cos(p.contact_angle_deg*pi/180);
  std::vector<double> groove_offsets;
  groove_offsets.reserve(p.groove_count);
  for (std::size_t i=0; i<p.groove_count; ++i)
    groove_offsets.push_back(normal_head_gradient*radius*std::cos(2*pi*(i+.5)/p.groove_count));
  const double evaporator_suction=groove_limit-*std::min_element(groove_offsets.begin(),groove_offsets.end());
  // A puddle occupying more than three quarters of the core diameter
  // lies outside the shallow-pool approximation.
  const double suction_floor=-normal_head_gradient*radius/2;
  const double groove_conductance=full_groove_conductance(p.groove_width,p.groove_depth)*p.liquid_flow_factor;
  const double core_conductance=pi*std::pow(radius,4)/8;
  if (!positive(vapor_fill_mass) || !positive(groove_limit) || !positive(evaporator_suction-suction_floor) ||
      !positive(groove_conductance) || !positive(core_conductance))
    throw Error("grooved_heat_pipe_range");
  if (p.fluid_charge<vapor_fill_mass) throw Error("grooved_heat_pipe_charge");

  const auto section_at=[&](double suction) {
    double liquid_area=0, liquid_conductance=0, shear_weight=0;
    for (double offset:groove_offsets) {
      const double local=suction+offset;
      const double sine=std::clamp(local/capillary_scale,0.0,1.0);
      // Beyond depinning, regularize the transition to a drained groove
      // over 15% of its critical suction. This is a reduced wetting law.
      const double wet=std::clamp(1-(local-groove_limit)/(.15*groove_limit),0.0,1.0);
      const double area=(groove_area-recessed_area(p.groove_width,sine))*wet;
      const double fraction=area/groove_area;
      const double partial_conductance=groove_conductance*fraction*fraction;
      liquid_area+=area;
      liquid_conductance+=partial_conductance*fraction;
      shear_weight+=partial_conductance*p.groove_width/groove_area;
    }
    double pool_area=0;
    if (normal_head_gradient>0 && suction<normal_head_gradient*radius) {
      const double cosine=std::clamp(suction/(normal_head_gradient*radius),-.5,1.0);
      const double sine=std::sqrt(1-cosine*cosine);
      pool_area=radius*radius*(std::acos(cosine)-cosine*sine);
      const double mean_depth=pool_area/(2*radius*sine);
      liquid_conductance+=pool_area*mean_depth*mean_depth/3;
      shear_weight+=pool_area*mean_depth/3;
    }
    const double open_fraction=1-pool_area/core_area;
    const double vapor_diameter=p.core_diameter*std::sqrt(open_fraction);
    const double liquid_resistance=p.liquid_viscosity/(p.liquid_density*liquid_conductance);
    const double vapor_resistance=p.vapor_viscosity/(p.vapor_density*core_conductance*open_fraction*open_fraction);
    // Approximate opposing interfacial stress by the equivalent vapor
    // duct's mean wall stress. Each parallel path contributes by its
    // conductance and interface width per liquid area.
    const double shear_resistance=vapor_resistance*vapor_diameter*shear_weight/(4*liquid_conductance);
    const Section section{liquid_area+pool_area,pool_area,liquid_resistance+vapor_resistance+shear_resistance,
                          1/vapor_diameter};
    if (!positive(section.resistance) || !positive(section.inverse_vapor_diameter))
      throw Error("grooved_heat_pipe_range");
    return section;
  };

  // Reuse cross-section geometry for every shooting iterate. Only the
  // axial integration depends on the trial heat load.
  constexpr std::size_t bins=2048;
  std::vector<Section> table;
  table.reserve(bins+1);
  for (std::size_t i=0; i<=bins; ++i)
    table.push_back(section_at(std::lerp(suction_floor,evaporator_suction,static_cast<double>(i)/bins)));
  const auto shoot=[&](double power) {
    double suction=evaporator_suction, liquid_volume=0, pool_volume=0, peak_reynolds=0;
    const auto rate=[&](double pressure,double fraction) {
      if (!std::isfinite(pressure)) throw Error("grooved_heat_pipe_range");
      const double index=bins*std::clamp((pressure-suction_floor)/(evaporator_suction-suction_floor),0.0,1.0);
      const auto i=std::min(static_cast<std::size_t>(index),bins-1);
      const auto interpolate=[&](auto member) {return std::lerp(table[i].*member,table[i+1].*member,index-i);};
      const double mass_flow=power*fraction/p.latent_heat;
      peak_reynolds=std::max(peak_reynolds,4*mass_flow*interpolate(&Section::inverse_vapor_diameter)/(pi*p.vapor_viscosity));
      return std::array{-axial_head_gradient-mass_flow*interpolate(&Section::resistance),
                        interpolate(&Section::liquid_area),interpolate(&Section::pool_area)};
    };
    const auto advance=[&](double length,double inlet_fraction,double outlet_fraction) {
      if (length==0) return;
      const double dx=length/p.steps_per_section;
      for (std::size_t i=0; i<p.steps_per_section; ++i) {
        const double first=static_cast<double>(i)/p.steps_per_section;
        const double last=static_cast<double>(i+1)/p.steps_per_section;
        const double middle=std::lerp(inlet_fraction,outlet_fraction,std::midpoint(first,last));
        const auto a=rate(suction,std::lerp(inlet_fraction,outlet_fraction,first));
        const auto b=rate(suction+dx*a[0]/2,middle);
        const auto c=rate(suction+dx*b[0]/2,middle);
        const auto d=rate(suction+dx*c[0],std::lerp(inlet_fraction,outlet_fraction,last));
        suction+=dx*(a[0]+2*b[0]+2*c[0]+d[0])/6;
        liquid_volume+=dx*(a[1]+2*b[1]+2*c[1]+d[1])/6;
        pool_volume+=dx*(a[2]+2*b[2]+2*c[2]+d[2])/6;
      }
    };
    advance(p.evaporator_length,0,1);
    advance(p.length-(p.evaporator_length+p.condenser_length),1,1);
    advance(p.condenser_length,1,0);
    if (!std::isfinite(suction) || !std::isfinite(liquid_volume) || !std::isfinite(pool_volume) ||
        !std::isfinite(peak_reynolds)) throw Error("grooved_heat_pipe_range");
    return Shot{suction,vapor_fill_mass+density_difference*liquid_volume,
                p.liquid_density*pool_volume,peak_reynolds};
  };

  const auto unloaded=shoot(0);
  if (p.fluid_charge<=unloaded.charge)
    return {0,unloaded.charge,unloaded.charge-p.fluid_charge,0,0};
  double lo=0,hi=1;
  auto trial=shoot(hi);
  for (int i=0; i<40 && trial.charge<p.fluid_charge && trial.condenser_suction>=suction_floor; ++i) {
    hi*=2;
    trial=shoot(hi);
  }
  if (trial.charge<p.fluid_charge) throw Error("grooved_heat_pipe_flooded");
  for (int i=0; i<40; ++i) {
    const double mid=std::midpoint(lo,hi);
    if (shoot(mid).charge<p.fluid_charge) lo=mid;
    else hi=mid;
  }
  const auto result=shoot(lo);
  if (result.condenser_suction<suction_floor) throw Error("grooved_heat_pipe_flooded");
  if (result.peak_reynolds>2300) throw Error("grooved_heat_pipe_vapor_regime");
  const double residual=result.charge-p.fluid_charge;
  if (!std::isfinite(residual) || !std::isfinite(result.pool_mass) ||
      std::abs(residual)>1e-9*p.fluid_charge) throw Error("grooved_heat_pipe_range");
  return {lo,unloaded.charge,residual,result.pool_mass,result.peak_reynolds};
}
} // namespace fcst::fluid
