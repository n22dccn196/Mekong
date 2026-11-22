(function(){
"use strict";
var base=(window.MEKONG_API_BASE||"").replace(/\/$/,"");
var stationGrid=document.getElementById("station-grid");
var benchmarkGrid=document.getElementById("benchmark-grid");
var modelSummary=document.getElementById("model-summary");
var overallState=document.getElementById("overall-state");
var connectionLabel=document.getElementById("connection-label");
var updatedAt=document.getElementById("updated-at");
var footerSource=document.getElementById("footer-source");
function esc(v){return String(v==null?"":v).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})}
function time(v){if(!v)return "—";var d=new Date(v);return isNaN(d)?"—":d.toLocaleString("en-GB",{timeZone:"UTC",month:"short",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false})+" UTC"}
function statusClass(s){if(s==="LIVE_VERIFIED"||s==="LIVE_AWAITING_NEXT_MEASUREMENT")return "live";if(s==="STALE"||s==="SOURCE_ERROR"||s==="METADATA_INCOMPLETE")return "stale";return "pending"}
function statusText(s){return ({LIVE_VERIFIED:"LIVE VERIFIED",LIVE_AWAITING_NEXT_MEASUREMENT:"LIVE · WAITING",LIVE_BLOCKED:"LIVE BLOCKED",STALE:"STALE",SOURCE_ERROR:"SOURCE ERROR",METADATA_INCOMPLETE:"METADATA CHECK"}[s]||String(s||"CHECKING").replace(/_/g," "))}
function chart(points){
 if(!points||points.length<2)return '<div class="chart-wrap"><div class="forecast-empty">Not enough recent measurements to draw a trend.</div></div>';
 var vals=points.map(function(p){return Number(p.water_level_m)}).filter(Number.isFinite);if(vals.length<2)return "";
 var w=520,h=110,pad=10,min=Math.min.apply(null,vals),max=Math.max.apply(null,vals),span=Math.max(max-min,.001);
 var coords=vals.map(function(v,i){return [pad+i*(w-2*pad)/(vals.length-1),h-pad-(v-min)*(h-2*pad)/span]});
 var line=coords.map(function(p,i){return (i?"L":"M")+p[0].toFixed(1)+" "+p[1].toFixed(1)}).join(" ");
 var area=line+" L "+coords[coords.length-1][0]+" "+(h-pad)+" L "+coords[0][0]+" "+(h-pad)+" Z",last=coords[coords.length-1];
 return '<div class="chart-wrap"><svg viewBox="0 0 '+w+' '+h+'" role="img" aria-label="Water level observations in the last 24 hours"><path class="chart-gridline" d="M10 20H510 M10 55H510 M10 90H510"/><path class="chart-area" d="'+area+'"/><path class="chart-line" d="'+line+'"/><circle class="chart-point" cx="'+last[0]+'" cy="'+last[1]+'" r="4"/></svg></div>';
}
function forecastCells(items){
 var wanted=[15,60,360];
 if(!items||!items.length)return '<div class="forecast-empty">Forecast hidden · feed, metadata or freshness check is not ready.</div>';
 return wanted.map(function(minutes){
  var f=items.find(function(x){return Number(x.horizon_minutes)===minutes}),label=minutes<60?"+15 MIN":minutes===60?"+1 HOUR":"+6 HOURS";
  if(!f)return '<div class="forecast-cell"><span>'+label+'</span><strong>—</strong><small>not verified</small></div>';
  return '<div class="forecast-cell"><span>'+label+'</span><strong>'+Number(f.predicted_water_level_m).toFixed(3)+' m</strong><small>target '+time(f.target_at_utc)+'</small></div>';
 }).join("");
}
function renderStations(data){
 if(!data||!data.length){stationGrid.innerHTML='<article class="empty-card"><p>No MRC station data is available. Forecasts remain blocked.</p></article>';return}
 stationGrid.innerHTML=data.map(function(s){
  var m=s.latest_measurement||{},status=s.status||"LIVE_BLOCKED",forecasts=s.forecast||[];
  return '<article class="station-card"><div class="station-card-head"><div><h3 class="station-name">'+esc(s.name||s.station_id)+'</h3><div class="station-id">MRC STATION '+esc(s.station_id)+'</div><div class="river-name">'+esc(s.river||"Mekong")+' · Viet Nam</div></div><span class="status-label '+statusClass(status)+'">'+esc(statusText(status))+'</span></div>'+
   '<div class="station-main"><div><div class="level-number">'+(m.water_level_m==null?"—":Number(m.water_level_m).toFixed(3))+'<small>m</small></div><div class="level-label">LATEST OBSERVED WATER LEVEL</div></div><div class="time-pair">MEASURED&nbsp; <b>'+esc(time(m.measured_at_utc))+'</b><br>RECEIVED&nbsp; <b>'+esc(time(m.received_at_utc))+'</b><br>AGE&nbsp; <b>'+(m.age_minutes==null?"—":esc(m.age_minutes)+" min")+'</b></div></div>'+
   chart(s.history_24h)+'<div class="forecast-strip">'+forecastCells(forecasts)+'</div><div class="station-id" style="padding:0 19px 12px">MODEL '+esc(s.model_version||"not serving")+' · MRC TELEMETRY</div></article>';
 }).join("");
}
function n(v,d){return v==null?"—":Number(v).toFixed(d||3)}
function renderBenchmark(data){
 var b=data&&data.benchmark;if(!b){modelSummary.innerHTML="";benchmarkGrid.innerHTML='<article class="empty-card">Benchmark report unavailable.</article>';return}
 modelSummary.innerHTML='<div class="metric"><span>PROTOCOL</span><strong>mrc-water-level-v1</strong></div><div class="metric"><span>DATA SOURCE</span><strong>MRC · real</strong></div><div class="metric"><span>STATIONS</span><strong>'+esc((b.stations||[]).join(" · "))+'</strong></div>';
 benchmarkGrid.innerHTML=(b.horizons||[]).map(function(h){
  var hold=h.holdout||{},ridge=hold.ridge||{},pers=hold.persistence||{};
  var intervalRows=(h.intervals||[]).map(function(x){return String(x.level)+"% "+String(x.status).replace(/_/g," ")}).join(" · ");
  return '<article class="benchmark-card"><h3>'+esc(h.horizon_minutes)+' minute outlook</h3><div class="benchmark-sub">'+esc(h.selected_model||"model")+' · holdout n='+esc(hold.n||"—")+'</div>'+
   '<div class="score-head score-row"><span>MODEL</span><b>MAE (m)</b><b>RMSE (m)</b></div><div class="score-row"><span>Ridge</span><b>'+n(ridge.mae)+'</b><b>'+n(ridge.rmse)+'</b></div><div class="score-row"><span>Persistence</span><b>'+n(pers.mae)+'</b><b>'+n(pers.rmse)+'</b></div><div class="band-note">Intervals: '+esc(intervalRows||"not calibrated")+'. Only verified intervals may be shown.</div></article>';
 }).join("");
}
function render(data){
 var good=(data.stations||[]).some(function(s){return s.status==="LIVE_VERIFIED"||s.status==="LIVE_AWAITING_NEXT_MEASUREMENT"});
 overallState.textContent=good?"LIVE DATA":"CHECK STATUS";overallState.className="state-chip "+(good?"state-live":"state-wait");
 connectionLabel.textContent=good?"MRC link active":"MRC link blocked or stale";document.querySelector(".live-dot").classList.toggle("on",good);
 updatedAt.textContent="Service checked "+time(data.server_time_utc);footerSource.textContent="Source status: "+(good?"live verification retained":"blocked or stale");
 renderStations(data.stations);renderBenchmark(data);
 var ph=data.benchmark&&data.benchmark.protocol_sha256;document.getElementById("protocol-hash").textContent=ph?"SHA-256 "+ph.slice(0,16)+"…":"Protocol hash pending";
}
async function refresh(){
 try{var response=await fetch(base+"/v1/public/overview",{method:"GET",cache:"no-store",headers:{Accept:"application/json"}});if(!response.ok)throw new Error("HTTP "+response.status);
 var data=await response.json();if(data.source_type!=="mrc_telemetry")throw new Error("source contract mismatch");render(data);
 }catch(error){connectionLabel.textContent="Service unavailable";overallState.textContent="OFFLINE";overallState.className="state-chip state-stale";footerSource.textContent="Source status: backend unavailable";stationGrid.innerHTML='<article class="empty-card"><p>Live service is not reachable. No cached or fixture forecast is displayed.</p></article>'}
}
document.querySelectorAll(".tab").forEach(function(button){button.addEventListener("click",function(){
 document.querySelectorAll(".tab").forEach(function(item){item.classList.remove("active");item.setAttribute("aria-selected","false")});
 document.querySelectorAll(".tab-panel").forEach(function(panel){panel.classList.remove("active");panel.hidden=true});
 button.classList.add("active");button.setAttribute("aria-selected","true");var panel=document.getElementById("panel-"+button.dataset.tab);panel.hidden=false;panel.classList.add("active");
})});
refresh();window.setInterval(refresh,30000);
})();