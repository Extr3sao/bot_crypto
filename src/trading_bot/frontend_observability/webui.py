"""Frontend-observability V1.2 — single-page read-only dashboard.

One embedded HTML document (no CDN, offline-safe) that renders the JSON
projections served by the same server.  The UI contains ZERO control
surface: no forms, no POST, no mutation endpoints — it only GETs read-only
projections.  All values originate in committed runtime artifacts (and,
when configured, the POC01 runtime's read-only campaign API); the UI never
computes accounting numbers.

V1.2-R2 (DEF-FE-001 fixed): URL hash == active tab == rendered view for
click navigation, direct hash load, manual hash change, browser back /
forward and page reload; auto-refresh and manual refresh preserve the
current route; unknown hashes fall back to #overview; two panels are never
active simultaneously.  DEF-FE-004 closed: the header always shows
DATA_SOURCE / REPORTS_ROOT / LAST_PERSISTED_AT / STALE_AGE and raises a
STALE_DATA banner instead of silently showing old campaign values.
"""

from __future__ import annotations

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>POC01 — Paper Observation (read-only)</title>
<style>
:root{--bg:#0d1117;--panel:#161b22;--panel2:#1c2330;--line:#2d333b;--fg:#e6edf3;--dim:#8b949e;
--green:#3fb950;--red:#f85149;--blue:#58a6ff;--amber:#d29922;--purple:#bc8cff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.45 ui-sans-serif,system-ui,"Segoe UI",Roboto,sans-serif}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
header{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:14px 20px;
border-bottom:1px solid var(--line);background:var(--panel);position:sticky;top:0;z-index:5}
header h1{font-size:16px;margin:0 12px 0 0}
.badge{display:inline-block;padding:2px 10px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid}
.b-paper{color:var(--blue);border-color:var(--blue)}
.b-real{color:var(--green);border-color:var(--green)}
.b-demo{color:var(--amber);border-color:var(--amber)}
.b-live{color:var(--red);border-color:var(--red);background:rgba(248,81,73,.08)}
.b-ok{color:var(--green);border-color:var(--green)}
.b-warn{color:var(--amber);border-color:var(--amber)}
.b-dim{color:var(--dim);border-color:var(--dim)}
.camp{color:var(--dim);font-size:12px}
#src{font-size:11px;color:var(--dim);flex-basis:100%}
#src b{color:var(--fg);font-weight:600}
.stale{color:var(--red);font-weight:700}
nav{display:flex;flex-wrap:wrap;gap:4px;padding:8px 20px;background:var(--panel);border-bottom:1px solid var(--line)}
nav a{padding:6px 12px;border-radius:8px;color:var(--dim);font-weight:600;font-size:13px}
nav a:hover{background:var(--panel2);text-decoration:none}
nav a.on{color:var(--fg);background:var(--panel2);outline:1px solid var(--line)}
main{padding:20px;max-width:1180px;margin:0 auto}
section{display:none}section.on{display:block}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:18px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}
.card .k{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.4px}
.card .v{font-size:24px;font-weight:700;margin-top:4px}
.card .s{font-size:12px;color:var(--dim);margin-top:2px}
.pos{color:var(--green)}.neg{color:var(--red)}.flat{color:var(--fg)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
.panel h2{margin:0 0 12px;font-size:14px;color:var(--dim);text-transform:uppercase;letter-spacing:.5px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:600;text-transform:uppercase;font-size:11px;letter-spacing:.4px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tr:hover td{background:rgba(88,166,255,.04)}
.frow{display:grid;grid-template-columns:220px 1fr 90px 90px;gap:10px;align-items:center;margin:6px 0}
.fbar{height:18px;background:var(--panel2);border-radius:6px;overflow:hidden;position:relative}
.fbar>span{position:absolute;inset:0;background:linear-gradient(90deg,#1f6feb,#58a6ff);border-radius:6px}
.frow .c{text-align:right;font-variant-numeric:tabular-nums}
.frow .p{color:var(--dim);text-align:right;font-variant-numeric:tabular-nums}
.chart{display:flex;align-items:flex-end;gap:14px;height:120px;margin:10px 0 4px}
.cbar{display:flex;flex-direction:column;align-items:center;gap:4px;flex:1;max-width:90px}
.cbar .bars{display:flex;align-items:flex-end;gap:3px;height:90px}
.cbar .b{width:14px;background:#1f6feb;border-radius:3px 3px 0 0}
.cbar .b.pnl-pos{background:var(--green)}.cbar .b.pnl-neg{background:var(--red)}
.cbar .d{color:var(--dim);font-size:11px}
.cbar .n{font-size:11px;font-variant-numeric:tabular-nums}
details{margin-top:6px}summary{cursor:pointer;color:var(--blue);font-size:12px}
pre{white-space:pre-wrap;word-break:break-word;background:var(--panel2);border:1px solid var(--line);
border-radius:8px;padding:10px;font-size:12px;max-height:420px;overflow:auto}
.err{background:rgba(248,81,73,.12);border:1px solid var(--red);border-radius:10px;padding:10px 14px;margin:14px 0}
.na{color:var(--dim);font-size:13px;padding:6px 0}
footer{color:var(--dim);font-size:12px;padding:18px 20px;border-top:1px solid var(--line);margin-top:24px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:860px){.grid2{grid-template-columns:1fr}.frow{grid-template-columns:130px 1fr 70px 70px}}
</style>
</head>
<body>
<header>
  <h1>POC01 · Paper Observation Campaign</h1>
  <span class="badge b-paper" id="badge-mode">PAPER</span>
  <span class="badge b-demo" id="badge-data">…</span>
  <span class="badge b-live" id="badge-live">LIVE DISABLED</span>
  <span class="badge b-dim" id="badge-campaign">…</span>
  <span class="badge b-dim" id="badge-provider">…</span>
  <span style="flex:1"></span>
  <label style="font-size:12px;color:var(--dim)"><input type="checkbox" id="auto"> auto 30s</label>
  <button id="refresh" style="background:var(--panel2);color:var(--fg);border:1px solid var(--line);
    border-radius:8px;padding:6px 12px;cursor:pointer">Refresh</button>
  <div id="src"></div>
</header>
<div id="stalebanner" class="err" style="display:none;margin:0;padding:8px 20px;border-radius:0"></div>
<nav id="tabs">
  <a href="#overview" data-t="overview" class="on">Overview</a>
  <a href="#funnel" data-t="funnel">Funnel</a>
  <a href="#agents" data-t="agents">Agents</a>
  <a href="#strategies" data-t="strategies">Strategies</a>
  <a href="#assets" data-t="assets">Assets</a>
  <a href="#decisions" data-t="decisions">Decisions</a>
  <a href="#trades" data-t="trades">Trades</a>
  <a href="#reports" data-t="reports">Reports</a>
  <a href="#replay" data-t="replay">Replay</a>
</nav>
<main>
  <div id="err" class="err" style="display:none"></div>
  <section id="s-overview" class="on">
    <div class="cards" id="ov-cards"></div>
    <div class="panel"><h2>Campaign window</h2><div id="ov-window" class="camp"></div></div>
    <div class="panel"><h2>Daily observations (canonical daily aggregates)</h2>
      <div class="chart" id="ov-chart"></div>
      <div id="ov-days"></div></div>
  </section>
  <section id="s-funnel"><div class="panel"><h2>Opportunity funnel</h2><div id="fun"></div></div></section>
  <section id="s-agents"><div class="panel"><h2>Agent conversation — structured artifacts only</h2>
    <div id="ag"></div></div></section>
  <section id="s-strategies"><div class="panel"><h2>Strategies</h2><div id="st"></div></div></section>
  <section id="s-assets"><div class="panel"><h2>Assets</h2><div id="as"></div></div></section>
  <section id="s-decisions"><div class="panel"><h2>Decisions</h2><div id="de"></div></div></section>
  <section id="s-trades">
    <div class="grid2">
      <div class="panel"><h2>Open positions</h2><div id="tr-open"></div></div>
      <div class="panel"><h2>Closed trades (canonical PnL passthrough)</h2><div id="tr-closed"></div></div>
    </div>
  </section>
  <section id="s-reports"><div class="panel"><h2>Reports (read-only, current campaign only)</h2><div id="rpEl"></div></div></section>
  <section id="s-replay"><div class="panel"><h2>Replay</h2><div id="reEl"></div></div></section>
</main>
<footer>read-only observability · zero control endpoints (all POST → 405) ·
PnL numbers are a passthrough of PaperBroker / reconciliation accounting ·
campaign: <span id="f-camp"></span></footer>
<script>
"use strict";
const TABS=["overview","funnel","agents","strategies","assets","decisions","trades","reports","replay"];
const $=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!==undefined)e.textContent=String(x);return e};
const fmt=(x,d=2)=>x==null?"—":Number(x).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});
const cls=x=>x==null?"flat":x>0?"pos":x<0?"neg":"flat";
const na=(msg)=>{const p=$("p","na",msg||"N/A");return p};
async function j(p){const r=await fetch(p,{headers:{Accept:"application/json"}});
  if(!r.ok){let d="";try{d=(await r.json()).detail||""}catch(e){}throw new Error(p+" -> "+r.status+(d?": "+d:""))}
  return r.json()}
function banner(msg){const b=document.getElementById("err");b.textContent=msg;b.style.display="block"}
function clearBanner(){document.getElementById("err").style.display="none"}
function badge(id,txt,c){const b=document.getElementById(id);b.textContent=txt;b.className="badge "+c}
function table(head,rows,num){const t=$("table");const tr=$("tr");
  head.forEach(h=>{const th=$("th",null,h);if(num.includes(h))th.classList.add("num");tr.appendChild(th)});
  t.appendChild(tr);
  rows.forEach(r=>{const tr=$("tr");r.forEach((c,i)=>{const td=$("td",null,c==null?"—":c);
    if(typeof c==="number"&&num.includes(head[i])){td.classList.add("num");td.classList.add(cls(c))}
    tr.appendChild(td)});t.appendChild(tr)});
  return t}
function setSrc(ov){const el=document.getElementById("src");el.textContent="";
  if(!ov){el.textContent="DATA_SOURCE: —";return}
  const parts=["DATA_SOURCE: "+(ov.data_source||"—")];
  if(ov.reports_root)parts.push("REPORTS_ROOT: "+ov.reports_root);
  if(ov.campaign_api)parts.push("CAMPAIGN_API: "+ov.campaign_api);
  if(ov.last_persisted_at)parts.push("LAST_PERSISTED_AT: "+ov.last_persisted_at);
  if(ov.stale_age_seconds!=null)parts.push("STALE_AGE: "+ov.stale_age_seconds+"s");
  const span=$("b",null,parts.join(" · "));
  el.appendChild(span);
  if(ov.api_error){el.appendChild($("b","stale"," · API fallback: "+ov.api_error))}
  const sb=document.getElementById("stalebanner");
  if(ov.stale){sb.textContent="STALE_DATA — artifact snapshot age "+ov.stale_age_seconds+
      "s exceeds threshold "+ov.stale_threshold_seconds+"s; values below are the last persisted snapshot";
    sb.style.display="block"}
  else{sb.style.display="none"}}
function renderHeader(ov){
  badge("badge-data",ov.data==="REAL_PUBLIC_MARKET"?"REAL PUBLIC MARKET":"DEMO FIXTURE",
    ov.data==="REAL_PUBLIC_MARKET"?"b-real":"b-demo");
  badge("badge-campaign",(ov.campaign_id||"no campaign")+" · state: "+(ov.campaign_state||"—"),"b-dim");
  const prov=(ov.provider_status||"—").toUpperCase();
  badge("badge-provider","provider: "+prov,prov==="OK"?"b-ok":"b-warn");
  document.getElementById("f-camp").textContent=ov.campaign_id||"—";
  setSrc(ov)}
function renderOverview(ov,dly){
  const oc=document.getElementById("ov-cards");oc.textContent="";
  const cards=[
    ["Equity",fmt(ov.equity),""],
    ["Realized PnL",fmt(ov.realized_pnl),cls(ov.realized_pnl)],
    ["Unrealized PnL",fmt(ov.unrealized_pnl),cls(ov.unrealized_pnl)],
    ["Net PnL",fmt(ov.net_pnl),cls(ov.net_pnl)],
    ["PnL today",fmt(ov.pnl_today),cls(ov.pnl_today)],
    ["Max drawdown",ov.max_drawdown==null?"—":fmt(ov.max_drawdown,4),ov.max_drawdown?"neg":"flat"],
    ["Market scans (today)",fmt(ov.scans_today,0),""],
    ["Proposals (today)",fmt(ov.proposals_today,0),""],
    ["Selected (today)",fmt(ov.selected_today,0),""],
    ["Risk accepts (today)",fmt(ov.risk_accepts_today,0),""],
    ["Risk rejects (today)",fmt(ov.risk_rejects_today,0),""],
    ["Trades today",fmt(ov.trades_today,0)+(ov.trades_today_date?" ("+ov.trades_today_date+")":""),
      (ov.ge_3_target&&ov.ge_3_target.met)?"pos":"flat"],
    ["Open positions",fmt(ov.open_positions,0),""],
    ["Closed trades",fmt(ov.closed_trades,0),""]];
  cards.forEach(([k,v,c])=>{const d=$("div","card");d.appendChild($("div","k",k));
    const vv=$("div","v",v);if(c)vv.classList.add(c);d.appendChild(vv);oc.appendChild(d)});
  const win=document.getElementById("ov-window");win.textContent="";
  const bi=ov.burn_in||{};const prog=ov.campaign_progress||{};
  win.textContent="burn-in/status: "+(bi.status||"—")+" · launch day (BURN_IN): "+(bi.launch_day_burn_in||"—")+
    " · counted window: "+(bi.counted_window_start||"—")+" → "+(bi.counted_window_end||"—")+
    " · completed valid days: "+(prog.valid_days??"—")+" / "+(prog.target_days??7);
  const ch=document.getElementById("ov-chart");ch.textContent="";
  const days=(dly&&dly.days)||[];
  const mx=Math.max(1,...days.map(d=>Math.max(d.trades||0,Math.abs(d.realized_pnl||0))));
  days.slice(-14).forEach(d=>{
    const col=$("div","cbar");const bars=$("div","bars");
    const bt=$("div","b");bt.style.height=(90*(d.trades||0)/mx)+"px";bt.title="trades: "+d.trades;
    const bp=$("div","b "+((d.realized_pnl||0)>=0?"pnl-pos":"pnl-neg"));
    bp.style.height=(90*Math.abs(d.realized_pnl||0)/mx)+"px";bp.title="realized pnl: "+d.realized_pnl;
    bars.appendChild(bt);bars.appendChild(bp);col.appendChild(bars);
    col.appendChild($("div","n",d.trades+(d.day_ge_3?" ✓3":"")));
    col.appendChild($("div","d",d.date.slice(5)));ch.appendChild(col)});
  document.getElementById("ov-days").textContent="";
  document.getElementById("ov-days").appendChild(table(
    ["date","scans","proposals","debates","no_trade","risk accepts","risk rejects","trades","≥3","realized PnL","max intraday DD","data-health ev"],
    days.map(d=>[d.date,d.scans,d.proposals,d.debates,d.no_trade,d.risk_accepts,d.risk_rejects,d.trades,d.day_ge_3?"YES":"no",d.realized_pnl,d.max_intraday_drawdown,d.data_health_events]),
    ["realized PnL","max intraday DD"]))}
function renderFunnel(fu){const fn=document.getElementById("fun");fn.textContent="";
  const counts=fu.counts||{};const conv=fu.conversions||{};const names=Object.keys(counts);
  const mainNames=names.filter(n=>!["NO_TRADE","RISK_REJECT","RISK_CALLS","BROKER_CALLS","CRITIQUES","REVISIONS"].includes(n));
  const mx2=Math.max(1,...mainNames.map(n=>counts[n]||0));
  names.forEach((n,i)=>{const row=$("div","frow");row.appendChild($("div",null,n));
    const bar=$("div","fbar");const sp=$("span");sp.style.width=(100*(counts[n]||0)/mx2)+"%";bar.appendChild(sp);row.appendChild(bar);
    row.appendChild($("div","c",counts[n]));
    const prev=names[i-1];row.appendChild($("div","p",prev?((conv[prev+"->"+n]!=null)?(100*conv[prev+"->"+n]).toFixed(1)+"%":"—"):""));
    fn.appendChild(row)})}
function renderAgents(ag){const box=document.getElementById("ag");box.textContent="";
  box.appendChild($("p","camp",ag.note||""));
  box.appendChild($("p","na","per-event agent messages: "+(ag.per_event_messages||"NOT_PERSISTED")));
  const a=ag.aggregates||{};
  box.appendChild(table(["metric","value"],
    Object.entries(a).map(([k,v])=>[k,v==null?"NOT_PERSISTED":v]),[]))}
function renderStrategies(st){const el=document.getElementById("st");el.textContent="";
  el.appendChild(table(
    ["strategy","evaluations","proposals","selected","trades","wins","losses","net PnL","expectancy","PF","sample"],
    (st.strategies||[]).map(s=>[s.strategy,s.evaluations,s.proposals,s.selected,s.trades,s.wins,s.losses,
      s.net_pnl==null?"—":fmt(s.net_pnl),s.expectancy==null?"—":fmt(s.expectancy,4),
      s.profit_factor==null?"—":fmt(s.profit_factor,3),s.sample]),
    ["net PnL","expectancy","PF"]))}
function renderAssets(asv){const el=document.getElementById("as");el.textContent="";
  el.appendChild(table(
    ["asset","proposals","selected","risk accepted","trades","net PnL","sample"],
    (asv.assets||[]).map(a=>[a.asset,a.proposals,a.selected,a.risk_accepted,a.trades,
      a.net_pnl==null?"—":fmt(a.net_pnl),a.sample]),["net PnL"]));
  const dh=asv.data_health||{};
  el.appendChild($("p","camp","data health — gaps: "+(dh.gaps??"—")+" · duplicate candles: "+(dh.duplicate_candles??"—")+
    " · stale events: "+(dh.stale_events??"—")+" · future events: "+(dh.future_events??"—")+
    " · provider failures: "+(dh.provider_failures??"—")+" · last market ts: "+(asv.last_market_timestamp_iso||"NOT_PERSISTED")+
    " · last scan: "+(asv.last_successful_scan_time||"—")))}
function renderDecisions(de){const el=document.getElementById("de");el.textContent="";
  const dm=de.campaign_aggregates||{};
  el.appendChild(table(["decision outcome","count"],
    [["SELECTED",dm.selected],["REJECTED",dm.rejected],["NO_TRADE",dm.no_trade],
     ["verifier VERIFIED",dm.verifier_verified],["verifier REJECTED",dm.verifier_rejected],
     ["selected with dissent",dm.selected_with_dissent],["blocked unresolved conflict",dm.blocked_unresolved_conflict]],[]));
  const rk=de.risk||{};
  el.appendChild($("h2",null,"Risk"));
  el.appendChild(table(["risk metric","value"],
    [["accepts",rk.accepts],["rejects",rk.rejects],["rejection rate",rk.rejection_rate]],[]));
  const rd=rk.reason_distribution||{};
  const reasons=Object.keys(rd).length?rd:{};
  el.appendChild($("h2",null,"Risk rejection reasons (typed)"));
  el.appendChild(reasons?table(["reason","count"],Object.entries(reasons),[]):na("INSUFFICIENT_DATA"));
  const br=de.block_reasons||{};
  el.appendChild($("h2",null,"Other block reasons"));
  el.appendChild(Object.keys(br).length?table(["reason","count"],Object.entries(br),[]):na("none recorded"));
  el.appendChild($("p","na","per-decision detail: "+(de.per_decision_detail||"NOT_PERSISTED")))}
function renderTrades(tr){const openEl=document.getElementById("tr-open");openEl.textContent="";
  const op=tr.open_positions||[];
  openEl.appendChild(op.length?table(
    ["symbol","side","entry","qty","opened","decision"],
    op.map(o=>[o.symbol||o.asset,o.side,o.entry_price,o.quantity??o.qty,
      o.opened_at_ms?new Date(o.opened_at_ms).toISOString():o.opened_at,o.decision_id]),["entry"]):
    $("p","camp","no open positions"));
  const ctEl=document.getElementById("tr-closed");ctEl.textContent="";
  const ct=tr.closed_trades||[];
  ctEl.appendChild(ct.length?table(
    ["asset","side","strategy","entry","exit","exit reason","realized PnL","regime","decision","closed_at"],
    ct.map(t=>[t.symbol||t.asset,t.side,t.strategy,t.entry_price,t.exit_price,t.exit_reason,t.pnl,
      t.regime,t.decision_id,t.closed_at]),["realized PnL"]):$("p","camp","no closed trades"));
  ctEl.appendChild($("p","camp","closed-trades PnL sum: "+fmt(tr.closed_trades_pnl_sum,6)+
    " · canonical realized PnL: "+fmt(tr.realized_pnl,6)+" · (frontend computes nothing)"))}
function renderReports(items){const el=document.getElementById("rpEl");el.textContent="";
  if(!items||!items.length){el.appendChild(na("no reports persisted for the current campaign"));return}
  const ul=$("ul");ul.style.cssText="columns:2;gap:24px";
  items.forEach(r=>{const li=$("li");const a=$("a",null,(r.campaign_id?r.campaign_id+"/":"")+r.name);
    a.href="/api/reports/content?path="+encodeURIComponent(r.path);
    a.setAttribute("download",r.name);li.appendChild(a);
    li.appendChild(document.createTextNode(" ("+r.bytes+" B)"));ul.appendChild(li)});
  el.appendChild(ul)}
function renderReplay(re){const el=document.getElementById("reEl");el.textContent="";
  el.appendChild($("p",null,"RUN_REPLAY = "+re.RUN_REPLAY+" · run-level replay CLI: "+re.run_level_replay_cli));
  el.appendChild(table(["step","available","evidence","detail"],
    (re.chain||[]).map(c=>[c.step,c.available?"available":"missing",c.evidence,c.detail||"—"]),[]));
  el.appendChild($("p","camp",re.note||""))}
async function loadAll(){
  clearBanner();
  const settled=await Promise.allSettled(
    ["/overview","/funnel","/agents","/strategies","/assets","/decisions","/trades","/reports","/replay","/daily"].map(j));
  const v=i=>settled[i].status==="fulfilled"?settled[i].value:null;
  const ov=v(0),fu=v(1),ag=v(2),st=v(3),asv=v(4),de=v(5),tr=v(6),rp=v(7),re=v(8),dly=v(9);
  renderHeader(ov||{});
  const failed=settled.filter(s=>s.status==="rejected");
  if(ov==null){const msg=failed.length?failed.map(f=>String(f.reason&&f.reason.message||f.reason)).join(" | "):"no data";
    banner("projection error: "+msg)}
  else if(failed.length){banner("partial projection errors: "+
    failed.map(f=>String(f.reason&&f.reason.message||f.reason)).join(" | "))}
  const guard=(fn,...args)=>{try{fn(...args)}catch(e){banner("render error: "+e)}};
  guard(renderOverview,ov||{data_source:"NONE"},dly);
  if(fu)guard(renderFunnel,fu);else document.getElementById("fun").textContent="INSUFFICIENT_DATA";
  if(ag)guard(renderAgents,ag);else document.getElementById("ag").textContent="INSUFFICIENT_DATA";
  if(st)guard(renderStrategies,st);else document.getElementById("st").textContent="INSUFFICIENT_DATA";
  if(asv)guard(renderAssets,asv);else document.getElementById("as").textContent="INSUFFICIENT_DATA";
  if(de)guard(renderDecisions,de);else document.getElementById("de").textContent="INSUFFICIENT_DATA";
  if(tr)guard(renderTrades,tr);else document.getElementById("tr-closed").textContent="INSUFFICIENT_DATA";
  if(rp)guard(renderReports,Array.isArray(rp)?rp:rp.reports);else document.getElementById("rpEl").textContent="INSUFFICIENT_DATA";
  if(re)guard(renderReplay,re);else document.getElementById("reEl").textContent="INSUFFICIENT_DATA";
}
/* ---- hash router (DEF-FE-001): hash == active tab == rendered view ---- */
function activate(tab){
  document.querySelectorAll("nav a").forEach(a=>a.classList.toggle("on",a.dataset.t===tab));
  document.querySelectorAll("main section").forEach(s=>s.classList.toggle("on",s.id==="s-"+tab));
}
function currentTab(){const h=(location.hash||"#overview").slice(1);return TABS.includes(h)?h:"overview"}
function route(){
  const tab=currentTab();
  if(!TABS.includes((location.hash||"#overview").slice(1))&&location.hash){
    location.replace("#overview");return}  // unknown hash -> safe fallback, no history entry
  activate(tab);
}
window.addEventListener("hashchange",route);
document.getElementById("refresh").addEventListener("click",()=>loadAll());
let timer=null;
document.getElementById("auto").addEventListener("change",e=>{
  if(e.target.checked){loadAll();timer=setInterval(loadAll,30000)}
  else if(timer){clearInterval(timer);timer=null}});
route();loadAll();
</script>
</body>
</html>
"""
