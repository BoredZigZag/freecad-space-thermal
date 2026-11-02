// SPDX-License-Identifier: MIT OR Apache-2.0
#pragma once
#include "fcst/radiation.hpp"
#include "fcst/thermal_transient.hpp"

namespace fcst::environment {
using radiation::Vec3;
using Quaternion = std::array<double,4>; // Unit w,x,y,z, vehicle to inertial.
struct Orbit {
  double body_radius_m, gravitational_parameter_m3_s2, radius_m, phase_rad;
  Quaternion plane_to_inertial{1,0,0,0};
};
struct Pose {
  double time;
  Quaternion rotation;
};
struct Joint {
  std::string id;
  std::vector<std::string> facets;
  Vec3 pivot_m, axis;
  std::vector<thermal::SchedulePoint> angles_rad; // factor is the signed joint angle.
};
struct Mission {
  // Seconds from a declared TAI epoch. No civil-time conversion is performed.
  std::string epoch_tai;
  double time_origin;
  std::optional<Orbit> orbit; // Absent for chamber/deep-space cases.
  Vec3 sun_direction_inertial;
  double solar_W_m2, albedo, body_exitance_W_m2, background_K;
  std::vector<Pose> attitude;
  std::vector<Joint> joints;
};
struct Frame {
  double time;
  bool eclipsed;
  std::shared_ptr<const radiation::Exchange> exchange;
  radiation::RadiosityOptions irradiation;
  double solar_W, albedo_W, body_ir_W;
};
struct History {
  std::vector<Frame> frames; // Right continuous between generated knots.
  std::size_t exchange_builds=0;
};
History prepare(const Mission&, const std::vector<radiation::Facet>&, const std::vector<std::string>& excluded,
                const radiation::Sampling&, double start, double end, double maximum_interval,
                std::span<const double> requested_boundaries={});
// The options' callback revision binds the complete canonical mission and mesh input.
thermal::TransientResult solve(thermal::Model, const History&, thermal::TransientOptions,
                               std::optional<thermal::TransientCheckpoint> restart={});
std::string inspect(std::string_view);
} // namespace fcst::environment
