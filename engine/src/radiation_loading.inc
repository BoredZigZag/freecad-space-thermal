// SPDX-License-Identifier: MIT OR Apache-2.0
// Included inside namespace fcst, using the shared bounded strict JSON parser.
namespace {
void validate_radiation_mapping(const thermal::Data& d,const std::vector<radiation::Facet>& facets) {
  if(d.radiation.size()!=1 || d.active_environment_ids.size()!=1 || d.radiation[0].environment_id!=d.active_environment_ids[0] || d.radiation[0].method!="diffuse") fail("radiation_mapping");
  std::set<std::string> expected(d.radiation[0].facet_ids.begin(),d.radiation[0].facet_ids.end()),actual;
  for(const auto& f:facets) { actual.insert(f.id); if(f.node>=d.nodes.size()) fail("radiation_mapping"); }
  for(const auto& id:d.radiation[0].excluded_facet_ids) expected.erase(id);
  if(actual!=expected) fail("radiation_mapping");
  auto canonical=Parser{d.canonical_snapshot}.parse(); Entities entities;
  for(const auto& entity:canonical.at("entities").arr()) entities.emplace(entity.at("id").str(),entity);
  for(const auto& f:facets) {
    const auto& declared=entities.at(f.id);
    const auto& declared_optics=entities.at(declared.at("optics_id").str());
    const bool back=declared.at("side").str()=="back"; const auto& assigned=back?f.back:f.front;
    if(!assigned.active || (back?f.front.active:f.back.active) ||
       declared_optics.at("specular_fraction").num()!=0 || declared_optics.at("transmissivity").num()!=0 ||
       assigned.solar_absorptance!=declared_optics.at("solar_absorptivity").num() || assigned.ir_emittance!=declared_optics.at("ir_emissivity").num()) fail("radiation_mapping");
    const auto& a=f.vertices[0];const auto& b=f.vertices[1];const auto& c=f.vertices[2];
    std::array<double,3> u{b[0]-a[0],b[1]-a[1],b[2]-a[2]},v{c[0]-a[0],c[1]-a[1],c[2]-a[2]};
    double area=.5*std::hypot(u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]);
    double expected_area=declared.at("area").at("value").num();
    if(std::abs(area-expected_area)>1e-10*expected_area) fail("radiation_mapping");
  }
}
template<std::size_t N> std::array<double,N> environment_vector(const J& value) {
  if(value.arr().size()!=N)fail("schema");
  std::array<double,N> result;
  for(std::size_t i=0;i<N;++i)result[i]=value.arr()[i].num();
  return result;
}
std::string inspect_environment(const J& value,const std::vector<radiation::Facet>& facets,
                                const std::vector<std::string>& excluded,const radiation::Sampling& sampling) {
  auto model=thermal::load(dump(value.at("thermal_input")));
  const auto& data=model.data();
  std::vector<radiation::Facet> active;
  for(const auto& f:facets)if(std::find(excluded.begin(),excluded.end(),f.id)==excluded.end())active.push_back(f);
  validate_radiation_mapping(data,active);
  const auto& id=data.active_environment_ids.front();
  auto env=std::find_if(data.environments.begin(),data.environments.end(),[&](const auto& e){return e.id==id;});
  if(env==data.environments.end() || env->time_scale!="TAI")fail("environment_epoch");
  const auto& m=value.at("mission");
  execution_keys(m,{"sun_direction_inertial","maximum_interval_s","attitude"},
                   {"orbit","albedo","body_exitance_W_m2","joints","case_optics"});
  auto case_facets=facets;
  if(m.has("case_optics")) {
    if(!data.case_id)fail("environment_case");
    std::set<std::string> overridden;
    for(const auto& overlay:m.at("case_optics").arr()) {
      execution_keys(overlay,{"facet_id","solar_absorptance","ir_emittance","condition"});
      auto facet_id=overlay.at("facet_id").str();
      auto f=std::find_if(case_facets.begin(),case_facets.end(),[&](const auto& item){return item.id==facet_id;});
      if(f==case_facets.end() || !overridden.insert(facet_id).second ||
         std::find(excluded.begin(),excluded.end(),facet_id)!=excluded.end())fail("environment_mapping");
      auto& optics=f->front.active?f->front:f->back;
      optics.solar_absorptance=overlay.at("solar_absorptance").num();
      optics.ir_emittance=overlay.at("ir_emittance").num();
      optics.dataset.condition=overlay.at("condition").str();
    }
  }
  environment::Mission mission{};
  mission.epoch_tai=env->epoch;
  mission.time_origin=env->time_origin;
  mission.solar_W_m2=env->solar_flux;
  mission.background_K=env->background_temperature;
  mission.sun_direction_inertial=environment_vector<3>(m.at("sun_direction_inertial"));
  if(m.has("albedo"))mission.albedo=m.at("albedo").num();
  if(m.has("body_exitance_W_m2"))mission.body_exitance_W_m2=m.at("body_exitance_W_m2").num();
  if(m.has("orbit")) {
    const auto& o=m.at("orbit");
    execution_keys(o,{"body_radius_m","gravitational_parameter_m3_s2","radius_m","phase_rad","plane_to_inertial"});
    mission.orbit=environment::Orbit{o.at("body_radius_m").num(),o.at("gravitational_parameter_m3_s2").num(),
      o.at("radius_m").num(),o.at("phase_rad").num(),environment_vector<4>(o.at("plane_to_inertial"))};
  }
  for(const auto& point:m.at("attitude").arr()) {
    execution_keys(point,{"time_s","rotation"});
    mission.attitude.push_back({point.at("time_s").num(),environment_vector<4>(point.at("rotation"))});
  }
  if(m.has("joints"))for(const auto& j:m.at("joints").arr()) {
    execution_keys(j,{"id","facets","pivot_m","axis","angles"});
    environment::Joint joint{j.at("id").str(),{},environment_vector<3>(j.at("pivot_m")),environment_vector<3>(j.at("axis")),{}};
    for(const auto& facet:j.at("facets").arr())joint.facets.push_back(facet.str());
    for(const auto& p:j.at("angles").arr()) {
      execution_keys(p,{"time_s","angle_rad"});
      joint.angles_rad.push_back({p.at("time_s").num(),p.at("angle_rad").num()});
    }
    mission.joints.push_back(std::move(joint));
  }
  const auto& settings=value.at("transient");
  auto options=execution_options(settings);
  J::O dependencies;
  for(auto key:{"facets","excluded_facets","sampling","mission"})if(value.has(key))dependencies.emplace(key,value.at(key));
  dependencies.emplace("preparation_hash",J(data.preparation_hash));
  options.callback_revision=thermal::thermal_digest(canonical(J(dependencies)));
  auto boundaries=options.output_times;
  for(const auto& schedule:options.schedules)for(const auto& point:schedule.points)boundaries.push_back(point.time);
  auto history=environment::prepare(mission,case_facets,excluded,sampling,options.start,options.end,
                                    m.at("maximum_interval_s").num(),boundaries);
  std::optional<thermal::TransientCheckpoint> restart;
  if(value.has("checkpoint"))restart=execution_checkpoint(value.at("checkpoint"));
  auto result=environment::solve(model,history,options,restart);
  auto out=transient_output(data,settings,result);
  J::A loading;
  for(const auto& frame:history.frames)loading.emplace_back(J::O{
    {"time_s",J(frame.time)},{"eclipsed",J(frame.eclipsed)},{"solar_W",J(frame.solar_W)},
    {"albedo_W",J(frame.albedo_W)},{"body_ir_W",J(frame.body_ir_W)}});
  out.emplace("loading_history",J(loading));
  out.emplace("exchange_builds",J(static_cast<double>(history.exchange_builds)));
  out.emplace("environment_dependency_sha256",J(options.callback_revision));
  return dump(J(out));
}
} // namespace
static std::string inspect_radiation(std::string_view input,bool steady,bool moving) {
  try {
    if(input.size()>1048576) fail("input_limit");
    auto value=Parser{input}.parse();
    auto fields=[](const J& object,std::initializer_list<std::string_view> allowed) {
      if(!object.isobj()) fail("schema");
      for(const auto& [key,v]:object.obj()) { (void)v; if(std::find(allowed.begin(),allowed.end(),key)==allowed.end()) fail("schema"); }
    };
    auto number=[](const J& v) { if(!v.isnum() || !std::isfinite(v.num())) fail("schema"); return v.num(); };
    auto integer=[&](const J& v) { auto x=number(v); if(x<0 || x>1000000000 || x!=std::floor(x)) fail("schema"); return static_cast<std::uint64_t>(x); };
    auto text=[](const J& v) { if(!v.isstr() || v.str().empty() || v.str().size()>256) fail("schema"); return v.str(); };
    auto array=[](const J& v)->const J::A& { if(!v.isarr()) fail("schema"); return v.arr(); };
    auto optical=[&](const J& v) {
      fields(v,{"solar_absorptance","ir_emittance","active","dataset"});
      if(!std::holds_alternative<bool>(v.at("active").v)) fail("schema");
      radiation::Optics o{number(v.at("solar_absorptance")),number(v.at("ir_emittance")),std::get<bool>(v.at("active").v)};
      const auto& d=v.at("dataset"); fields(d,{"solar_band","infrared_band","valid_temperature_K","condition","absolute_uncertainty","provenance"});
      o.dataset.solar_band=text(d.at("solar_band"));o.dataset.infrared_band=text(d.at("infrared_band"));
      const auto& range=array(d.at("valid_temperature_K"));const auto& uncertainty=array(d.at("absolute_uncertainty"));
      if(range.size()!=2 || uncertainty.size()!=2) fail("schema");
      o.dataset.minimum_temperature=number(range[0]);o.dataset.maximum_temperature=number(range[1]);
      o.dataset.absolute_uncertainty={number(uncertainty[0]),number(uncertainty[1])};
      o.dataset.condition=text(d.at("condition"));o.dataset.provenance=text(d.at("provenance"));return o;
    };
    if(moving)execution_keys(value,{"schema_version","facets","sampling","mission","thermal_input","transient"},
                             {"excluded_facets","checkpoint"});
    else fields(value,{"schema_version","facets","excluded_facets","sampling","temperatures_K","environment","thermal_input"});
    if(integer(value.at("schema_version"))!=1) fail("version");
    std::vector<radiation::Facet> facets;
    for(const auto& f:array(value.at("facets"))) {
      fields(f,{"id","surface_id","group","node","vertices_m","front","back"});
      radiation::Facet facet; facet.id=text(f.at("id")); facet.surface_id=text(f.at("surface_id")); facet.group=text(f.at("group"));
      facet.node=static_cast<std::size_t>(integer(f.at("node"))); facet.front=optical(f.at("front")); facet.back=optical(f.at("back"));
      const auto& vertices=array(f.at("vertices_m")); if(vertices.size()!=3) fail("schema");
      for(std::size_t i=0;i<3;++i) { const auto& xyz=array(vertices[i]); if(xyz.size()!=3) fail("schema"); for(std::size_t k=0;k<3;++k) facet.vertices[i][k]=number(xyz[k]); }
      facets.push_back(std::move(facet));
    }
    std::vector<std::string> excluded;
    if(value.has("excluded_facets")) for(const auto& id:array(value.at("excluded_facets"))) excluded.push_back(text(id));
    radiation::Sampling sampling;
    sampling.maximum_entries=4096;
    fields(value.at("sampling"),{"seed","samples","maximum_entries"});
    sampling.seed=integer(value.at("sampling").at("seed")); sampling.samples=integer(value.at("sampling").at("samples"));
    if(value.at("sampling").has("maximum_entries")) sampling.maximum_entries=static_cast<std::size_t>(integer(value.at("sampling").at("maximum_entries")));
    if(sampling.maximum_entries>4096 || sampling.samples>1000000 || facets.size()>4096) fail("radiation_limit");
    if(moving)return inspect_environment(value,facets,excluded,sampling);
    radiation::RadiosityOptions options;
    fields(value.at("environment"),{"temperature_K","solar_incident_W_m2"});
    options.background_temperature=number(value.at("environment").at("temperature_K"));
    if(value.at("environment").has("solar_incident_W_m2")) for(const auto& v:array(value.at("environment").at("solar_incident_W_m2"))) options.solar_incident.push_back(number(v));
    radiation::Mesh mesh(std::move(facets),std::move(excluded));
    auto exchange=std::make_shared<const radiation::Exchange>(radiation::trace(mesh,sampling));
    std::vector<double> temperatures;
    if(value.has("temperatures_K")) for(const auto& t:array(value.at("temperatures_K"))) temperatures.push_back(number(t));
    J::O out{{"status",J("passed")},{"execution_mode",J("fcst_native")},{"schema_version",J(1.0)},
      {"source_revision",J(thermal::thermal_backend_capabilities().source_revision)},
      {"input_sha256",J(thermal::thermal_digest(input))},
      {"estimator",J("area-uniform cosine-hemisphere Bernoulli hit fraction")},
      {"stream_version",J("splitmix64-fnv1a-surface-side-v1")},
      {"confidence_method",J("pointwise two-sided Wilson 95 percent; ensemble qualification uses Bonferroni")},
      {"seed",J(static_cast<double>(sampling.seed))},{"samples_per_patch",J(static_cast<double>(sampling.samples))}};
    if(steady) {
      if(!value.has("thermal_input") || value.has("temperatures_K")) fail("schema");
      auto model=thermal::load(dump(value.at("thermal_input"))); const auto& d=model.data();
      validate_radiation_mapping(d,mesh.facets());
      if(!options.solar_incident.empty()) fail("radiation_mapping");
      if(d.case_id) fail("radiation_case_not_supported");
      auto env=std::find_if(d.environments.begin(),d.environments.end(),[&](const auto& e) { return e.id==d.active_environment_ids[0]; });
      if(env==d.environments.end() || options.background_temperature!=env->background_temperature || env->solar_flux!=0) fail("radiation_mapping");
      auto powers=radiation::bind(exchange,d.radiation[0].id,d.active_environment_ids[0],options);
      thermal::Assembly assembly(std::move(model),std::move(powers)); auto result=thermal::solve_steady(assembly);
      if(result.solve.status!=thermal::SolveStatus::converged || !result.balance) throw thermal::Error("radiation_steady_failed");
      temperatures=result.balance->temperature;
      out.emplace("energy_defect_W",J(result.balance->energy_defect));
      out.emplace("model_hash",J(assembly.model().data().model_hash));
    } else if(value.has("thermal_input") || temperatures.empty()) fail("schema");
    auto evaluated=radiation::evaluate(*exchange,temperatures,options);
    J::A patches,raw,edges,ts;
    for(double t:temperatures) ts.emplace_back(t);
    for(std::size_t i=0;i<exchange->patches().size();++i) {
      const auto& p=exchange->patches()[i];
      patches.emplace_back(J::O{{"id",J(p.id)},{"surface_id",J(p.surface_id)},{"node",J(static_cast<double>(p.node))},{"back",J(p.back)},
        {"area_m2",J(p.area)},{"escape",J(exchange->escape()[i])},{"radiosity_W_m2",J(evaluated.radiosity[i])},
        {"internal_W",J(evaluated.internal_power[i])},{"environment_W",J(evaluated.environment[i])},
        {"optical_dataset",J(J::O{{"solar_band",J(p.optics.dataset.solar_band)},{"infrared_band",J(p.optics.dataset.infrared_band)},
          {"valid_temperature_K",J(J::A{J(p.optics.dataset.minimum_temperature),J(p.optics.dataset.maximum_temperature)})},
          {"condition",J(p.optics.dataset.condition)},{"provenance",J(p.optics.dataset.provenance)},
          {"absolute_uncertainty",J(J::A{J(p.optics.dataset.absolute_uncertainty[0]),J(p.optics.dataset.absolute_uncertainty[1])})}})}});
      const auto& r=exchange->raw()[i]; J::A counts;
      constexpr double quantile=1.959963984540054;
      for(const auto& c:r.counts) {
        auto interval=radiation::wilson(c.hits,r.samples,quantile);
        counts.emplace_back(J::O{{"target",J(static_cast<double>(c.target))},{"hits",J(static_cast<double>(c.hits))},
          {"estimate",J(interval.estimate)},{"lower",J(interval.lower)},{"upper",J(interval.upper)}});
      }
      auto escape_interval=radiation::wilson(r.escaped,r.samples,quantile);
      auto blocked_interval=radiation::wilson(r.blocked,r.samples,quantile);
      raw.emplace_back(J::O{{"source",J(static_cast<double>(i))},{"samples",J(static_cast<double>(r.samples))},
        {"escaped",J(static_cast<double>(r.escaped))},{"blocked",J(static_cast<double>(r.blocked))},{"counts",J(counts)},
        {"escape_interval",J(J::A{J(escape_interval.lower),J(escape_interval.upper)})},
        {"blocked_interval",J(J::A{J(blocked_interval.lower),J(blocked_interval.upper)})},
        {"unlisted_zero_hit_upper",J(radiation::wilson(0,r.samples,quantile).upper)}});
    }
    // Bounded first page; the native Exchange API supports subsequent pages.
    for(const auto& e:exchange->page(0,std::min<std::size_t>(4096,exchange->edges().size()))) edges.emplace_back(J::O{
      {"first",J(static_cast<double>(e.first))},{"second",J(static_cast<double>(e.second))},{"area_factor_m2",J(e.area_factor)}});
    const auto& diagnostics=exchange->diagnostics();
    out.emplace("patches",J(patches)); out.emplace("raw",J(raw)); out.emplace("edges",J(edges)); out.emplace("temperatures_K",J(ts));
    out.emplace("edge_count",J(static_cast<double>(exchange->edges().size())));
    out.emplace("maximum_raw_reciprocity",J(diagnostics.maximum_raw_reciprocity)); out.emplace("maximum_correction",J(diagnostics.maximum_correction));
    out.emplace("linear_defect_W_m2",J(evaluated.linear_defect));
    return dump(J(out));
  } catch(const thermal::Error& e) { return dump(J(J::O{{"status",J("failed")},{"code",J(e.code)}})); }
    catch(const Error& e) { return dump(J(J::O{{"status",J("failed")},{"code",J(e.code)}})); }
    catch(...) { return "{\"status\":\"failed\",\"code\":\"radiation_schema\"}"; }
}

std::string radiation::inspect(std::string_view input,bool steady) { return inspect_radiation(input,steady,false); }
std::string environment::inspect(std::string_view input) { return inspect_radiation(input,false,true); }
