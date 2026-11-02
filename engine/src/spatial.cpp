// SPDX-License-Identifier: MIT OR Apache-2.0
#include "fcst/spatial.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <set>

namespace fcst::spatial {
namespace {
using thermal::Error;
double finite(double v) { if (!std::isfinite(v)) throw Error("range"); return v; }
double positive(double v) { if (!(finite(v)>0)) throw Error("spatial_geometry"); return v; }
Vector sub(Vector a,Vector b) { for (std::size_t i=0;i<3;++i) a[i]-=b[i]; return a; }
double dot(Vector a,Vector b) { double v=0; for (std::size_t i=0;i<3;++i) v+=a[i]*b[i];return finite(v); }
Vector cross(Vector a,Vector b) { return {a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]}; }
Vector mul(const thermal::Tensor& k,Vector v) { Vector r{};for (std::size_t i=0;i<3;++i) r[i]=dot(k[i],v);return r; }
// Reference derivatives map through the inverse metric/Jacobian, supporting shells in any plane.
Quadrature quadrature(const Cell& c,std::span<const Point> points,std::vector<double> shape,std::vector<Vector> reference,double weight,bool shell) {
  thermal::Tensor j{};
  for (std::size_t i=0;i<c.points.size();++i) {
    const auto delta=sub(points[c.points[i]].position,points[c.points[0]].position);
    for (std::size_t a=0;a<3;++a) for (std::size_t b=0;b<3;++b) j[a][b]+=delta[a]*reference[i][b];
  }
  Vector a{j[0][0],j[1][0],j[2][0]}, b{j[0][1],j[1][1],j[2][1]}, d{j[0][2],j[1][2],j[2][2]};
  std::vector<Vector> gradient(reference.size()); double measure=0;
  if (shell) {
    const double aa=dot(a,a),bb=dot(b,b),ab=dot(a,b),det=positive(aa*bb-ab*ab);
    if (det<=1e-24*aa*bb) throw Error("spatial_geometry",c.id);
    measure=std::sqrt(det)*positive(c.thickness);
    for (std::size_t i=0;i<reference.size();++i) for (std::size_t k=0;k<3;++k)
      gradient[i][k]=finite(((bb*reference[i][0]-ab*reference[i][1])*a[k]+(aa*reference[i][1]-ab*reference[i][0])*b[k])/det);
  } else {
    const double det=positive(dot(a,cross(b,d)));
    if (det<=1e-12*std::sqrt(dot(a,a)*dot(b,b)*dot(d,d))) throw Error("spatial_geometry",c.id);
    measure=det;
    const auto u=cross(b,d),v=cross(d,a),w=cross(a,b);
    for (std::size_t i=0;i<reference.size();++i) for (std::size_t k=0;k<3;++k)
      gradient[i][k]=finite((reference[i][0]*u[k]+reference[i][1]*v[k]+reference[i][2]*w[k])/det);
  }
  // Enforce partition-of-unity in floating point, independently of absolute coordinates.
  for (std::size_t k=0;k<3;++k) {gradient[0][k]=0;for (std::size_t i=1;i<gradient.size();++i)gradient[0][k]-=gradient[i][k];}
  return {positive(measure*weight),std::move(shape),std::move(gradient)};
}
double area(const Surface& s,std::span<const Point> points) {
  const auto a=sub(points[s.points[1]].position,points[s.points[0]].position),b=sub(points[s.points[2]].position,points[s.points[0]].position);
  return positive(std::sqrt(dot(cross(a,b),cross(a,b)))/2);
}
}
PreparedCell prepare(Cell c,std::span<const Point> points) {
  const std::map<std::string,std::size_t> sizes{{"tri3",3},{"quad4",4},{"tet4",4},{"hex8",8}};
  if (!sizes.contains(c.topology)) throw Error("unsupported_element",c.id);
  if (c.points.size()!=sizes.at(c.topology)) throw Error("spatial_connectivity",c.id);
  std::set<std::size_t> unique;
  for (auto p:c.points) {
    if (p>=points.size() || !unique.insert(p).second) throw Error("spatial_connectivity",c.id);
    for (double x:points[p].position) (void)finite(x);
  }
  const bool shell=c.topology=="tri3" || c.topology=="quad4";
  if ((!shell && c.thickness!=0) || (shell && !(c.thickness>0))) throw Error("spatial_thickness",c.id);
  PreparedCell out{c,{}};
  if (c.topology=="tri3") {
    // Three-point degree-two rule also integrates nonlinear material interpolation.
    for (std::size_t p=0;p<3;++p) {std::vector<double> n(3,1.0/6);n[p]=2.0/3;
      out.quadrature.push_back(quadrature(c,points,n,{{-1,-1,0},{1,0,0},{0,1,0}},1.0/6,true));}
  } else if (c.topology=="tet4") {
    const double a=(5+3*std::sqrt(5.0))/20,b=(5-std::sqrt(5.0))/20;
    for (std::size_t p=0;p<4;++p) {std::vector<double> n(4,b);n[p]=a;
      out.quadrature.push_back(quadrature(c,points,n,{{-1,-1,-1},{1,0,0},{0,1,0},{0,0,1}},1.0/24,false));}
  } else {
    const std::vector<Vector> signs=shell?std::vector<Vector>{{-1,-1,0},{1,-1,0},{1,1,0},{-1,1,0}}:
      std::vector<Vector>{{-1,-1,-1},{1,-1,-1},{1,1,-1},{-1,1,-1},{-1,-1,1},{1,-1,1},{1,1,1},{-1,1,1}};
    const double g=1/std::sqrt(3.0);
    if(!shell)for(int x:{-1,0,1})for(int y:{-1,0,1})for(int z:{-1,0,1}) {
      std::vector<Vector> derivatives;
      for(const auto& s:signs)derivatives.push_back({s[0]*(1+s[1]*y)*(1+s[2]*z)/8,
        s[1]*(1+s[0]*x)*(1+s[2]*z)/8,s[2]*(1+s[0]*x)*(1+s[1]*y)/8});
      (void)quadrature(c,points,std::vector<double>(8,0),std::move(derivatives),1,false);
    }
    for (int x:{-1,1}) for (int y:{-1,1}) for (int z:{-1,1}) {
      if (shell && z==1) continue;
      Vector q{x*g,y*g,shell?0:z*g}; std::vector<double> n; std::vector<Vector> dn;
      for (const auto& s:signs) {
        const double denominator=shell?4.0:8.0;
        n.push_back((1+s[0]*q[0])*(1+s[1]*q[1])*(shell?1:1+s[2]*q[2])/denominator);
        dn.push_back({s[0]*(1+s[1]*q[1])*(shell?1:1+s[2]*q[2])/denominator,
          s[1]*(1+s[0]*q[0])*(shell?1:1+s[2]*q[2])/denominator,
          shell?0:s[2]*(1+s[0]*q[0])*(1+s[1]*q[1])/denominator});
      }
      out.quadrature.push_back(quadrature(c,points,n,dn,1,shell));
    }
    // Folded or warped shell/solid mappings must fail before assembly.
    const auto& p0=points[c.points[0]].position;
    if (shell) {
      auto normal=cross(sub(points[c.points[1]].position,p0),sub(points[c.points[3]].position,p0));
      const double scale=std::sqrt(positive(dot(normal,normal)));
      for (auto p:c.points) if (std::abs(dot(sub(points[p].position,p0),normal))>1e-10*scale*std::max(1.0,std::sqrt(dot(sub(points[p].position,p0),sub(points[p].position,p0))))) throw Error("spatial_nonplanar",c.id);
      for (std::size_t i=0;i<4;++i) {
        auto edge1=sub(points[c.points[(i+1)%4]].position,points[c.points[i]].position);
        auto edge2=sub(points[c.points[(i+2)%4]].position,points[c.points[(i+1)%4]].position);
        if (dot(cross(edge1,edge2),normal)<=0) throw Error("spatial_geometry",c.id);
      }
    }
  }
  return out;
}
void attach(thermal::Data& d,Discretization mesh) {
  std::set<std::size_t> nodes; std::set<std::string> ids;
  if (mesh.points.empty() || mesh.cells.empty()) throw Error("spatial_empty");
  for (const auto& p:mesh.points) if (p.node>=d.nodes.size() || !nodes.insert(p.node).second || !ids.insert(p.id).second) throw Error("spatial_identity");
  std::vector<bool> used(mesh.points.size());
  for (const auto& e:mesh.cells) {
    if (!ids.insert(e.cell.id).second || e.cell.material>=d.materials.size()) throw Error("spatial_identity",e.cell.id);
    const auto& m=d.materials[e.cell.material];
    for (auto p:e.cell.points) used[p]=true;
    for (const auto& q:e.quadrature) {
      const double origin=d.nodes[mesh.points[e.cell.points[0]].node].temperature;
      double initial=origin;for (std::size_t i=1;i<e.cell.points.size();++i)initial+=q.shape[i]*(d.nodes[mesh.points[e.cell.points[i]].node].temperature-origin);
      const double rho=m.density.sample(initial).value;
      (void)m.tensor(initial);(void)m.specific_heat.sample(initial);
      for (std::size_t i=0;i<e.cell.points.size();++i) {
        auto& node=d.nodes[mesh.points[e.cell.points[i]].node];
        if (node.material_index) throw Error("spatial_storage_overlap",node.id);
        if (node.classification==thermal::NodeClass::capacitive) node.spatial_storage.emplace_back(e.cell.material,positive(q.volume*q.shape[i]*rho));
      }
    }
  }
  if (std::find(used.begin(),used.end(),false)!=used.end()) throw Error("spatial_unassigned");
  for (auto n:nodes) {
    auto& node=d.nodes[n]; if (node.classification!=thermal::NodeClass::capacitive) continue;
    double capacity=0;for (auto [m,mass]:node.spatial_storage)capacity=finite(capacity+mass*d.materials[m].specific_heat.sample(node.temperature).value);
    if (std::abs(capacity-node.capacity)>1e-10*std::max(capacity,node.capacity)) throw Error("spatial_capacity_mismatch",node.id);
  }
  for (const auto& s:mesh.surfaces) {
    if (!ids.insert(s.id).second || s.points.size()!=3 || std::set<std::size_t>(s.points.begin(),s.points.end()).size()!=3) throw Error("spatial_identity",s.id);
    for (auto p:s.points) if (p>=mesh.points.size()) throw Error("spatial_reference",s.id);
    (void)area(s,mesh.points); (void)finite(s.value);(void)finite(s.ambient);
    if (s.kind!="flux" && s.kind!="power" && s.kind!="convection") throw Error("unsupported_boundary",s.id);
    if (s.ambient<0 || (s.kind=="convection" && s.value<0) || (s.kind!="convection" && s.ambient!=0)) throw Error("range",s.id);
  }
  for (const auto& c:mesh.contacts) {
    if (!ids.insert(c.id).second || c.from.empty() || c.to.empty()) throw Error("spatial_identity",c.id);
    std::set<std::size_t> endpoints;
    for (const auto* side:{&c.from,&c.to}) {
      double sum=0;for (auto [n,w]:*side) {if(n>=d.nodes.size() || !endpoints.insert(n).second)throw Error("spatial_reference",c.id);sum+=positive(w);}
      if (std::abs(sum-1)>1e-12) throw Error("spatial_weight",c.id);
    }
    (void)positive(c.area);(void)positive(c.coefficient);(void)positive(c.maximum_power);
    if (!std::isfinite(c.gap) || c.gap<0 || !std::isfinite(c.minimum_temperature) || c.minimum_temperature<0 || !std::isfinite(c.maximum_temperature) || c.maximum_temperature<=c.minimum_temperature) throw Error("range",c.id);
    if (c.kind!="contact" && c.kind!="insulation" && c.kind!="mli" && c.kind!="heat_pipe") throw Error("unsupported_contact",c.id);
    if ((c.kind=="insulation" && c.gap==0) || (c.kind=="mli" && c.coefficient>1) || c.provenance.empty()) throw Error("spatial_calibration",c.id);
    // Contact h and heat-pipe G describe closed/calibrated links. A gap is only modeled by k*A/gap insulation.
    if (c.kind!="insulation" && c.gap!=0) throw Error("unsupported_gap",c.id);
  }
  d.spatial=std::make_shared<const Discretization>(std::move(mesh));
}
bool nonlinear(const Discretization& mesh,const thermal::Data& d) {
  for (const auto& e:mesh.cells) if (!d.materials[e.cell.material].conductivity.constant() || d.materials[e.cell.material].tensor_law) return true;
  return std::any_of(mesh.contacts.begin(),mesh.contacts.end(),[](const auto& c){return c.kind=="mli";});
}
Evaluation evaluate(const Discretization& mesh,const thermal::Data& d,std::span<const double> t,bool jacobian) {
  if (t.size()!=d.nodes.size()) throw Error("dimension");
  Evaluation out;out.conductive.resize(t.size());out.load.resize(t.size());out.environment.resize(t.size());
  for (const auto& e:mesh.cells) try {
    const auto& m=d.materials[e.cell.material];const auto n=e.cell.points.size(); Vector flux{};double volume=0;
    for (const auto& q:e.quadrature) {
      Vector gradient{};const double origin=t[mesh.points[e.cell.points[0]].node];double temperature=origin;
      for (std::size_t i=0;i<n;++i) {
        double value=t[mesh.points[e.cell.points[i]].node];(void)m.tensor(value);
        temperature+=q.shape[i]*(value-origin);
        for (std::size_t k=0;k<3;++k)gradient[k]+=q.gradient[i][k]*(value-origin);
      }
      const auto tensor=m.tensor_sample(temperature);const auto& k=tensor.value;const auto law=m.conductivity.sample(temperature);
      if (jacobian && law.discontinuous) throw Error("nondifferentiable");
      const auto kg=mul(k,gradient);volume+=q.volume;
      for (std::size_t a=0;a<3;++a)flux[a]-=q.volume*kg[a];
      for (std::size_t i=0;i<n;++i) {
        auto row=mesh.points[e.cell.points[i]].node;
        out.conductive[row]=finite(out.conductive[row]-q.volume*dot(q.gradient[i],kg));
        if (jacobian) for (std::size_t j=0;j<n;++j) {
          double derivative=dot(q.gradient[i],mul(k,q.gradient[j]));
          derivative+=q.shape[j]*dot(q.gradient[i],mul(tensor.derivative,gradient));
          out.jacobian.push_back({row,mesh.points[e.cell.points[j]].node,finite(q.volume*derivative)});
        }
      }
    }
    for (double& v:flux)v=finite(v/volume);out.cell_flux.push_back(flux);
  } catch (Error& error) {error.entity_id=e.cell.id;throw;}
  for (const auto& s:mesh.surfaces) {
    const double a=area(s,mesh.points);
    if (s.kind=="convection") {
      // Exact consistent triangle boundary mass matrix: A/12*(1+delta_ij).
      for (std::size_t i=0;i<3;++i) {
        const auto row=mesh.points[s.points[i]].node;
        for (std::size_t j=0;j<3;++j) {const auto col=mesh.points[s.points[j]].node;const double h=s.value*a*(i==j?2:1)/12;
          out.environment[row]=finite(out.environment[row]+h*(s.ambient-t[col]));if(jacobian)out.jacobian.push_back({row,col,h});}
      }
    } else {
      const double power=s.kind=="flux"?finite(s.value*a):s.value;
      for (auto p:s.points)out.load[mesh.points[p].node]=finite(out.load[mesh.points[p].node]+power/3);
    }
  }
  for (const auto& c:mesh.contacts) try {
    double a=0,b=0;
    for (auto [n,w]:c.from) {if(t[n]<c.minimum_temperature || t[n]>c.maximum_temperature)throw Error("range");a+=w*t[n];}
    for (auto [n,w]:c.to) {if(t[n]<c.minimum_temperature || t[n]>c.maximum_temperature)throw Error("range");b+=w*t[n];}
    double g=c.kind=="heat_pipe"?c.coefficient:c.area*c.coefficient;
    if (c.kind=="insulation")g/=c.gap;
    double power=g*(a-b),da=g,db=-g;
    if (c.kind=="mli") {const double sigma=5.670374419e-8;power=g*sigma*(a-b)*(a+b)*(a*a+b*b);da=4*g*sigma*a*a*a;db=-4*g*sigma*b*b*b;}
    if (std::abs(finite(power))>c.maximum_power)throw Error("range");
    for (int side:{0,1})for (auto [row,w]:side==0?c.from:c.to) {
      const double sign=side==0?-1.0:1.0;out.conductive[row]=finite(out.conductive[row]+sign*w*power);
      if (jacobian) {for (auto [col,v]:c.from)out.jacobian.push_back({row,col,finite(-sign*w*da*v)});
        for (auto [col,v]:c.to)out.jacobian.push_back({row,col,finite(-sign*w*db*v)});}
    }
  } catch (Error& error) {error.entity_id=c.id;throw;}
  return out;
}
} // namespace fcst::spatial
