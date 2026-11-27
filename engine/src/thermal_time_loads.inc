// SPDX-License-Identifier: MIT OR Apache-2.0
// Owned time-power data bindings for transient requests.
struct TimePowerPoint { double time, left, right; };

double sample_time_power(const std::vector<TimePowerPoint>& points,double t) {
  auto hi=std::upper_bound(points.begin(),points.end(),t,
    [](double time,const TimePowerPoint& p){return time<p.time;});
  if(hi==points.begin())return hi->left;
  const auto& lo=*(hi-1);
  if(hi==points.end() || t==lo.time)return lo.right;
  return std::lerp(lo.right,hi->left,(t-lo.time)/(hi->time-lo.time));
}

std::vector<TimePowerPoint> time_power_points(const J& row,double start,double end) {
  constexpr std::size_t limit=10000;
  const auto& input=row.at("points").arr();
  if(input.size()<2 || input.size()>limit)fail("time_load_limit");
  std::vector<TimePowerPoint> points;
  for(const auto& p:input) {
    if(p.arr().size()!=2)fail("time_load_point");
    const double time=p.at(0).num(),watts=p.at(1).num();
    if(!std::isfinite(time) || !std::isfinite(watts) ||
       (!points.empty() && (time<=points.back().time || !std::isfinite(time-points.back().time))))
      fail("time_load_axis");
    points.push_back({time,watts,watts});
  }
  if(!row.has("period_s"))return points;
  const double period=row.at("period_s").num();
  if(!std::isfinite(period) || period<=0 || points.front().time!=0 || start<0 || end<=start)
    fail("time_load_period");
  const double last=sample_time_power(points,period),first=points.front().right;
  const auto boundary=std::lower_bound(points.begin(),points.end(),period,
    [](const TimePowerPoint& p,double time){return p.time<time;});
  const auto per_cycle=static_cast<std::size_t>(boundary-points.begin());
  const double count=std::floor(end/period)+1;
  if(!std::isfinite(count) || count>static_cast<double>((limit-1)/per_cycle))fail("time_load_limit");
  const auto cycles=static_cast<std::size_t>(count);
  std::vector<TimePowerPoint> repeated;
  repeated.reserve(cycles*per_cycle+1);
  auto append=[&](double time,double left,double right) {
    if(!std::isfinite(time) || (!repeated.empty() && time<=repeated.back().time))fail("time_load_axis");
    repeated.push_back({time,left,right});
  };
  for(std::size_t cycle=0;cycle<cycles;++cycle) {
    const double origin=static_cast<double>(cycle)*period;
    append(origin,cycle?last:first,first);
    for(auto p=points.begin()+1;p!=boundary;++p)append(origin+p->time,p->left,p->right);
  }
  append(static_cast<double>(cycles)*period,last,first);
  return repeated;
}

void bind_time_power(const J& tables,const thermal::Model& model,thermal::TransientOptions& options,
                     std::vector<thermal::PowerBinding>& powers) {
  if(tables.arr().empty() || tables.arr().size()>1024)fail("time_load_limit");
  std::map<std::string,const thermal::Load*> loads;
  for(const auto& load:model.data().loads)if(load.active && load.expression_id)loads.emplace(load.id,&load);
  std::map<double,bool> knots;
  std::size_t total=0;
  for(const auto& row:tables.arr()) {
    execution_keys(row,{"load_id","points"},{"period_s"});
    const auto id=row.at("load_id").str();
    auto load=loads.find(id);
    if(load==loads.end())throw thermal::Error("time_load_reference",id);
    auto points=std::make_shared<const std::vector<TimePowerPoint>>(time_power_points(row,options.start,options.end));
    total+=points->size();
    if(total>100000)fail("time_load_limit");
    for(const auto& p:*points)if(p.time>options.start && p.time<=options.end) {
      auto& jump=knots[p.time];
      jump=jump || p.left!=p.right;
      if(knots.size()>10000)fail("time_load_limit");
    }
    powers.push_back({id,thermal::PowerKind::load,{load->second->node},{},
      [points](double t,std::span<const double>,bool){return thermal::PowerEvaluation{{sample_time_power(*points,t)},{}};}});
    loads.erase(load);
  }
  for(const auto& [time,jump]:knots)options.callback_knots.push_back({time,jump});
}
