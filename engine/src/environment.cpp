// SPDX-License-Identifier: MIT OR Apache-2.0
#include "fcst/environment.hpp"
#include <algorithm>
#include <cmath>
#include <numbers>
#include <set>

namespace fcst::environment {
namespace {
using thermal::Error;
constexpr double pi=std::numbers::pi, sigma=5.670374419e-8;
double finite(double x) {
  if(!std::isfinite(x)) throw Error("environment_range");
  return x;
}
Vec3 scale(Vec3 v,double s) { for(double& x:v)x*=s; return v; }
Vec3 add(Vec3 a,const Vec3& b) { for(std::size_t i=0;i<3;++i)a[i]+=b[i]; return a; }
Vec3 subtract(Vec3 a,const Vec3& b) { return add(a,scale(b,-1)); }
double dot(const Vec3& a,const Vec3& b) { return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]; }
Vec3 cross(const Vec3& a,const Vec3& b) { return {a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]}; }
Vec3 unit(Vec3 v) {
  double n=finite(std::hypot(v[0],v[1],v[2]));
  if(n<=0)throw Error("environment_direction");
  return scale(v,1/n);
}
Quaternion validate_rotation(Quaternion q) {
  double n=finite(std::hypot(std::hypot(q[0],q[1]),std::hypot(q[2],q[3])));
  if(std::abs(n-1)>1e-10)throw Error("environment_rotation");
  for(auto& x:q)x/=n;
  return q;
}
Vec3 rotate(const Quaternion& q,Vec3 v,bool inverse=false) {
  Vec3 axis{q[1],q[2],q[3]};
  auto twice=scale(cross(axis,v),2);
  return add(v,add(scale(twice,inverse?-q[0]:q[0]),cross(axis,twice)));
}
template<class Point> void validate_points(const std::vector<Point>& points,double start) {
  if(points.empty() || points.size()>4096 || points.front().time>start)throw Error("environment_schedule");
  double previous=-std::numeric_limits<double>::infinity();
  for(const auto& p:points) {
    if(finite(p.time)<=previous)throw Error("environment_schedule");
    if(std::isfinite(previous))finite(p.time-previous);
    previous=p.time;
  }
}
template<class Point> const Point& at(const std::vector<Point>& points,double t) {
  return *std::prev(std::upper_bound(points.begin(),points.end(),t,[](double time,const Point& p){return time<p.time;}));
}
double joint_angle(const Joint& joint,double time) {
  const auto& points=joint.angles_rad;
  const auto& left=at(points,time);
  const auto* right=&left+1;
  if(right==points.data()+points.size())return left.factor;
  return std::lerp(left.factor,right->factor,(time-left.time)/(right->time-left.time));
}
Quaternion attitude(const std::vector<Pose>& points,double time) {
  const auto& left=at(points,time);
  auto a=validate_rotation(left.rotation);
  const auto* right=&left+1;
  if(right==points.data()+points.size())return a;
  auto b=validate_rotation(right->rotation);
  double cosine=0;
  for(std::size_t i=0;i<a.size();++i)cosine+=a[i]*b[i];
  if(cosine<0)for(auto& x:b)x=-x;
  cosine=std::clamp(std::abs(cosine),0.,1.);
  double fraction=(time-left.time)/(right->time-left.time);
  double alpha=1-fraction,beta=fraction;
  if(cosine<.999999) {
    double angle=std::acos(cosine);
    alpha=std::sin(alpha*angle)/std::sin(angle);
    beta=std::sin(beta*angle)/std::sin(angle);
  }
  double length=0;
  for(std::size_t i=0;i<a.size();++i) { a[i]=alpha*a[i]+beta*b[i];length+=a[i]*a[i]; }
  for(auto& x:a)x/=std::sqrt(length);
  return a;
}
struct Circle {
  Quaternion plane{1,0,0,0};
  double rate=0,phase=0,ratio=0,shadow_center=0,shadow_half_width=0;
  Circle(const Orbit& orbit,Vec3 sun) {
    if(finite(orbit.body_radius_m)<=0 || finite(orbit.radius_m)<=orbit.body_radius_m ||
       finite(orbit.gravitational_parameter_m3_s2)<=0)throw Error("environment_orbit");
    plane=validate_rotation(orbit.plane_to_inertial);
    rate=finite(std::sqrt(orbit.gravitational_parameter_m3_s2/orbit.radius_m)/orbit.radius_m);
    if(rate<=0)throw Error("environment_orbit");
    phase=std::remainder(finite(orbit.phase_rad),2*pi);
    ratio=orbit.body_radius_m/orbit.radius_m;
    auto local=rotate(plane,sun,true);
    shadow_center=std::atan2(-local[1],-local[0]);
    double projected=std::hypot(local[0],local[1]), threshold=std::sqrt((1-ratio)*(1+ratio));
    if(projected>threshold)shadow_half_width=std::acos(threshold/projected);
  }
  double angle(double time) const { return finite(phase+rate*time); }
  bool eclipse(double time) const { return std::abs(std::remainder(angle(time)-shadow_center,2*pi))<shadow_half_width; }
  void transitions(std::map<double,bool>& events,double start,double end) const {
    if(shadow_half_width==0)return;
    for(bool entry:{true,false}) {
      double boundary=shadow_center+(entry?-shadow_half_width:shadow_half_width);
      double cycle=std::floor((angle(start)-boundary)/(2*pi));
      if(std::abs(cycle)>1e12)throw Error("environment_limit");
      for(unsigned i=0;i<4098;++i,++cycle) {
        double time=finite((boundary+cycle*(2*pi)-phase)/rate);
        if(time>end)break;
        if(time>=start && !events.emplace(time,entry).second)throw Error("environment_schedule");
        if(i==4097)throw Error("environment_limit");
      }
    }
  }
};
bool visible(const radiation::Mesh& mesh,std::size_t facet,Vec3 origin,const Vec3& normal,const Vec3& direction) {
  for(std::size_t k=0;k<3;++k)if(normal[k]!=0)
    origin[k]=std::nextafter(origin[k],std::copysign(std::numeric_limits<double>::infinity(),normal[k]));
  return !mesh.intersect({origin,direction},facet);
}
void irradiate(Frame& frame,const radiation::Mesh& mesh,const Mission& mission,Vec3 sun,Vec3 body,double ratio) {
  const auto& exchange=*frame.exchange;
  auto count=exchange.patches().size();
  std::vector<double> solar(count),view(count);
  double phase_cos=std::clamp(-dot(sun,body),-1.,1.), phase=std::acos(phase_cos);
  // Lambert sphere phase law. Uniform effective disk radiance at the vehicle.
  double reflected=mission.albedo*mission.solar_W_m2*(2./3.)*
    std::max(0.,(std::sin(phase)+(pi-phase)*phase_cos)/pi);
  // Midpoint quadrature in cosine and azimuth over the apparent disk.
  constexpr int radial_bins=8, azimuth_bins=24;
  std::vector<Vec3> disk;
  double disk_weight=0;
  if(ratio>0 && (reflected>0 || mission.body_exitance_W_m2>0 || mission.background_K>0)) {
    auto tangent=unit(cross(std::abs(body[0])<.8?Vec3{1,0,0}:Vec3{0,1,0},body));
    auto bitangent=cross(body,tangent);
    double width=ratio*ratio/(1+std::sqrt((1-ratio)*(1+ratio)));
    disk_weight=2*width/(radial_bins*azimuth_bins);
    for(int r=0;r<radial_bins;++r) {
      double delta=width*(r+.5)/radial_bins;
      double mu=1-delta, radial=std::sqrt(delta*(2-delta));
      for(int a=0;a<azimuth_bins;++a) {
        double azimuth=2*pi*(a+.5)/azimuth_bins;
        disk.push_back(unit(add(scale(body,mu),add(scale(tangent,radial*std::cos(azimuth)),
                                                   scale(bitangent,radial*std::sin(azimuth))))));
      }
    }
  }
  for(std::size_t i=0;i<mesh.facets().size();++i) {
    const auto& f=mesh.facets()[i];
    auto edges=cross(subtract(f.vertices[1],f.vertices[0]),subtract(f.vertices[2],f.vertices[0]));
    double area=.5*std::hypot(edges[0],edges[1],edges[2]);
    auto center=scale(add(f.vertices[0],add(f.vertices[1],f.vertices[2])),1./3.);
    for(bool back:{false,true}) {
      auto index=mesh.patch(i,back);
      if(!index)continue;
      auto n=scale(unit(edges),back?-1:1);
      if(!frame.eclipsed && mission.solar_W_m2>0 && dot(n,sun)>0 && visible(mesh,i,center,n,sun))
        solar[*index]+=area*mission.solar_W_m2*dot(n,sun);
      for(const auto& ray:disk) {
        double projection=dot(n,ray);
        if(projection>0 && visible(mesh,i,center,n,ray))view[*index]+=area*disk_weight*projection;
      }
    }
  }
  frame.irradiation.background_temperature=mission.background_K;
  frame.irradiation.infrared_incident.resize(count);
  double background=finite(sigma*std::pow(mission.background_K,4));
  bool has_solar=false;
  for(std::size_t i=0;i<count;++i) {
    double area=exchange.patches()[i].area, escape=exchange.escape()[i];
    double occupied=std::min(view[i]/area,escape);
    double body_ir=occupied*mission.body_exitance_W_m2;
    frame.irradiation.infrared_incident[i]=finite(body_ir+(escape-occupied)*background);
    double reflected_W=occupied*area*reflected;
    frame.solar_W=finite(frame.solar_W+solar[i]);
    frame.albedo_W=finite(frame.albedo_W+reflected_W);
    frame.body_ir_W=finite(frame.body_ir_W+area*body_ir);
    solar[i]=finite((solar[i]+reflected_W)/area);
    has_solar|=solar[i]>0;
  }
  if(has_solar)frame.irradiation.solar_incident=std::move(solar);
}
} // namespace

History prepare(const Mission& mission,const std::vector<radiation::Facet>& facets,const std::vector<std::string>& excluded,
                const radiation::Sampling& sampling,double start,double end,double interval,
                std::span<const double> requested_boundaries) {
  if(finite(end)<=finite(start) || finite(interval)<=0 || (end-start)/interval>4094 ||
     facets.empty() || facets.size()>4096 || mission.joints.size()>4096 ||
     !sampling.samples || sampling.samples>1000000 || sampling.maximum_entries>65536)
    throw Error("environment_limit");
  for(double x:{mission.solar_W_m2,mission.albedo,mission.body_exitance_W_m2,mission.background_K})
    if(finite(x)<0)throw Error("environment_range");
  if(mission.albedo>1 || mission.background_K>10000 ||
     (!mission.orbit && (mission.albedo!=0 || mission.body_exitance_W_m2!=0)))throw Error("environment_range");
  if(mission.epoch_tai.empty() || mission.epoch_tai.size()>64)throw Error("environment_epoch");
  finite(mission.time_origin);
  validate_points(mission.attitude,start);
  for(const auto& p:mission.attitude)validate_rotation(p.rotation);
  auto sun=unit(mission.sun_direction_inertial);
  std::optional<Circle> circle;
  if(mission.orbit)circle.emplace(*mission.orbit,sun);
  // Arithmetic used to compute a boundary can differ by a few representable
  // times from the same boundary supplied in a load or output schedule.
  std::set<double> preferred{start,end};
  if(requested_boundaries.size()>1000000)throw Error("environment_limit");
  auto prefer=[&](double time){if(finite(time)>=start && time<=end)preferred.insert(time);};
  for(double time:requested_boundaries)prefer(time);
  for(const auto& point:mission.attitude)prefer(point.time);
  for(const auto& joint:mission.joints) {
    validate_points(joint.angles_rad,start);
    for(const auto& point:joint.angles_rad)prefer(point.time);
    if(preferred.size()>1000000)throw Error("environment_limit");
  }
  auto snap=[&](double time) {
    auto after=preferred.lower_bound(time);
    double nearest=after==preferred.end()?*preferred.rbegin():*after;
    if(after!=preferred.begin()) {
      double before=*std::prev(after);
      if(std::abs(time-before)<std::abs(time-nearest))nearest=before;
    }
    double bound=nearest;
    for(unsigned i=0;i<4;++i)bound=std::nextafter(bound,time);
    return bound==time?nearest:time;
  };
  std::map<double,bool> transitions;
  if(circle) {
    std::map<double,bool> relative;
    circle->transitions(relative,start-mission.time_origin,end-mission.time_origin);
    for(const auto& [time,entry]:relative) {
      double absolute=snap(finite(time+mission.time_origin));
      if(absolute<start || absolute>end || !transitions.emplace(absolute,entry).second)throw Error("environment_schedule");
    }
  }
  std::set<double> times{start,end};
  auto add_time=[&](double t){if(t>start && t<end)times.insert(t);};
  for(const auto& [t,entry]:transitions){(void)entry;add_time(t);prefer(t);}
  for(std::size_t i=1;static_cast<double>(i)*interval<end-start;++i)add_time(snap(start+static_cast<double>(i)*interval));
  for(const auto& p:mission.attitude)add_time(p.time);

  std::map<std::string,std::size_t> facet_index;
  for(std::size_t i=0;i<facets.size();++i)if(!facet_index.emplace(facets[i].id,i).second)throw Error("environment_mapping");
  std::vector<std::vector<std::size_t>> members;
  std::vector<Vec3> axes;
  std::set<std::size_t> assigned;
  std::set<std::string> joints;
  for(const auto& joint:mission.joints) {
    if(joint.id.empty() || !joints.insert(joint.id).second || joint.facets.empty())throw Error("environment_mapping");
    for(double x:joint.pivot_m)finite(x);
    axes.push_back(unit(joint.axis));
    for(const auto& p:joint.angles_rad){finite(p.factor);add_time(p.time);}
    members.emplace_back();
    for(const auto& id:joint.facets) {
      auto found=facet_index.find(id);
      if(found==facet_index.end() || !assigned.insert(found->second).second)throw Error("environment_mapping");
      members.back().push_back(found->second);
    }
  }
  if(times.size()>4096 || times.size()*facets.size()>262144)throw Error("environment_limit");
  History history;
  std::optional<radiation::Mesh> mesh;
  std::shared_ptr<const radiation::Exchange> exchange;
  std::vector<double> previous;
  std::uint64_t rays=0;
  std::size_t exchange_entries=0;
  bool eclipsed=circle && circle->eclipse(start-mission.time_origin);
  for(double time:times) {
    if(auto event=transitions.find(time);event!=transitions.end())eclipsed=event->second;
    std::vector<double> angles;
    for(const auto& joint:mission.joints)angles.push_back(joint_angle(joint,time));
    if(!mesh || angles!=previous) {
      auto moved=facets;
      for(std::size_t j=0;j<angles.size();++j) {
        const auto& pivot=mission.joints[j].pivot_m;
        double s=std::sin(angles[j]/2);
        Quaternion rotation{std::cos(angles[j]/2),axes[j][0]*s,axes[j][1]*s,axes[j][2]*s};
        for(auto i:members[j])for(auto& v:moved[i].vertices)v=add(pivot,rotate(rotation,subtract(v,pivot)));
      }
      mesh.emplace(std::move(moved),excluded);
      rays+=mesh->patches().size()*sampling.samples;
      if(rays>16000000)throw Error("environment_limit");
      exchange=std::make_shared<const radiation::Exchange>(radiation::trace(*mesh,sampling));
      exchange_entries+=exchange->edges().size()+exchange->diagnostics().raw_entries;
      if(exchange_entries>262144)throw Error("environment_limit");
      previous=std::move(angles);
      ++history.exchange_builds;
    }
    auto rotation=attitude(mission.attitude,time);
    Vec3 body{};
    if(circle) {
      double angle=circle->angle(time-mission.time_origin);
      body=rotate(rotation,rotate(circle->plane,{-std::cos(angle),-std::sin(angle),0}),true);
    }
    Frame frame{time,eclipsed,exchange,{},0,0,0};
    irradiate(frame,*mesh,mission,rotate(rotation,sun,true),body,circle?circle->ratio:0);
    history.frames.push_back(std::move(frame));
  }
  return history;
}
thermal::TransientResult solve(thermal::Model model,const History& history,thermal::TransientOptions options,
                               std::optional<thermal::TransientCheckpoint> restart) {
  const auto& data=model.data();
  if(data.radiation.size()!=1 || data.active_environment_ids.size()!=1 ||
     data.radiation.front().environment_id!=data.active_environment_ids.front() ||
     data.radiation.front().method!="diffuse" || history.frames.empty() ||
     history.frames.front().time!=options.start || history.frames.back().time!=options.end ||
     !options.callback_events.empty())throw Error("environment_mapping");
  const auto& radiation_id=data.radiation.front().id;
  const auto& environment_id=data.active_environment_ids.front();
  auto bindings=std::make_shared<std::vector<std::vector<thermal::PowerBinding>>>();
  std::vector<double> times;
  std::size_t dependency_count=0;
  for(const auto& frame:history.frames) {
    if(!frame.exchange || (!times.empty() && finite(frame.time)<=times.back()))throw Error("environment_schedule");
    if(!times.empty()) {
      bool before=history.frames[times.size()-1].eclipsed;
      options.callback_events.push_back({frame.time,environment_id,before!=frame.eclipsed?"eclipse":"environment",
        before?1.:0.,frame.eclipsed?1.:0.});
    }
    times.push_back(frame.time);
    auto powers=radiation::bind(frame.exchange,radiation_id,environment_id,frame.irradiation);
    dependency_count+=powers.front().dependencies.size();
    if(dependency_count>262144)throw Error("environment_limit");
    if(!bindings->empty() && powers.front().affected_nodes!=bindings->front().front().affected_nodes)
      throw Error("environment_mapping");
    bindings->push_back(std::move(powers));
  }
  auto active=bindings->front();
  auto knots=std::make_shared<const std::vector<double>>(std::move(times));
  for(std::size_t i=0;i<active.size();++i) {
    active[i].evaluate=[bindings,knots,i](double time,std::span<const double> t,bool jacobian) {
      auto pos=std::upper_bound(knots->begin(),knots->end(),time);
      if(pos==knots->begin() || time>knots->back())throw Error("environment_schedule");
      auto index=static_cast<std::size_t>(pos-knots->begin()-1);
      return (*bindings)[index][i].evaluate(time,t,jacobian);
    };
  }
  return thermal::solve_transient(thermal::Assembly(std::move(model),std::move(active)),options,std::move(restart));
}
} // namespace fcst::environment
