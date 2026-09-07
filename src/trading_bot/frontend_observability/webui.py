"""Frontend-observability V1.1 — single-page read-only dashboard.

One embedded HTML document (no CDN, offline-safe) that renders the JSON
projections served by the same server.  The UI contains ZERO control
surface: no forms, no POST, no mutation endpoints — it only GETs read-only
projections.  All values originate in committed runtime artifacts; the UI
never computes accounting numbers.
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
.tl{list-style:none;margin:0;padding:0}
.tl li{display:flex;gap:10px;padding:7px 0;border-bottom:1px solid var(--line);align-items:baseline}
.chip{min-width:170px;font-weight:700;font-size:12px}
.c-prop{color:var(--blue)}.c-crit{color:var(--amber)}.c-dec-sel{color:var(--green)}
.c-dec-no{color:var(--dim)}.c-dec-rej{color:var(--red)}.c-ver{color:var(--purple)}
.c-risk-a{color:var(--green)}.c-risk-r{color:var(--red)}.c-fill{color:var(--blue)}
.c-rev{color:var(--amber)}.c-mkt{color:var(--dim)}
.tl .meta{color:var(--dim);font-size:12px;flex:1}
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
  <span class="camp" id="asof"></span>
  <span style="flex:1"></span>
  <label style="font-size:12px;color:var(--dim)"><input type="checkbox" id="auto"> auto 30s</label>
  <button id="refresh" style="background:var(--panel2);color:var(--fg);border:1px solid var(--line);
    border-radius:8px;padding:6px 12px;cursor:pointer">Refresh</button>
</header>
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
    <div class="panel"><h2>Daily observations (canonical daily aggregates)</h2>
      <div class="chart" id="ov-chart"></div>
      <div id="ov-days"></div></div>
  </section>
  <section id="s-funnel"><div class="panel"><h2>Opportunity funnel</h2><div id="fun"></div></div></section>
  <section id="s-agents"><div class="panel"><h2>Agent conversation — structured artifacts only</h2>
    <ul class="tl" id="ag"></ul></div></section>
  <section id="s-strategies"><div class="panel"><h2>Strategies</h2><div id="st"></div></div></section>
  <section id="s-assets"><div class="panel"><h2>Assets</h2><div id="as"></div></div></section>
  <section id="s-decisions"><div class="panel"><h2>Decisions</h2><div id="de"></div></div></section>
  <section id="s-trades">
    <div class="grid2">
      <div class="panel"><h2>Open positions</h2><div id="tr-open"></div></div>
      <div class="panel"><h2>Closed trades (canonical PnL passthrough)</h2><div id="tr-closed"></div></div>
    </div>
  </section>
  <section id="s-reports"><div class="panel"><h2>Reports (read-only)</h2><div id="rp"></div></div></section>
  <section id="s-replay"><div class="panel"><h2>Replay</h2><div id="re"></div></div></section>
</main>
<footer>read-only observability · zero control endpoints (all POST → 405) ·
PnL numbers are a passthrough of PaperBroker / reconciliation accounting ·
campaign: <span id="f-camp"></span></footer>
<script>
"use strict";
const $=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!==undefined)e.textContent=String(x);return e};
const fmt=(x,d=2)=>x==null?"—":Number(x).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});
const cls=x=>x==null?"flat":x>0?"pos":x<0?"neg":"flat";
async function j(p){const r=await fetch(p,{headers:{Accept:"application/json"}});return r.json()}
function err(e){const b=document.getElementById("err");b.textContent="projection error: "+e;b.style.display="block"}
function clearErr(){document.getElementById("err").style.display="none"}
function badge(id,txt,c){const b=document.getElementById(id);b.textContent=txt;b.className="badge "+c}
const chipFor=ev=>{
  const e=String(ev||"").toLowerCase();
  if(e.includes("decision.selected"))return["c-dec-sel",ev];
  if(e.includes("decision.no_trade"))return["c-dec-no",ev];
  if(e.includes("decision.reject"))return["c-dec-rej",ev];
  if(e.includes("verif"))return["c-ver",ev];
  if(e.includes("risk.approve"))return["c-risk-a",ev];
  if(e.includes("risk.reject"))return["c-risk-r",ev];
  if(e.includes("fill")||e.includes("open")||e.includes("close"))return["c-fill",ev];
  if(e.includes("revis"))return["c-rev",ev];
  if(e.includes("crit")||e.includes("counter"))return["c-crit",ev];
  if(e.includes("prop"))return["c-prop",ev];
  return["c-mkt",ev];
};
function table(head,rows,num){const t=$("table");const tr=$("tr");
  head.forEach(h=>{const th=$("th",null,h);if(num.includes(h))th.classList.add("num");tr.appendChild(th)});
  t.appendChild(tr);
  rows.forEach(r=>{const tr=$("tr");r.forEach((c,i)=>{const td=$("td",null,c==null?"—":c);
    if(typeof c==="number"&&num.includes(head[i])){td.classList.add("num");td.classList.add(cls(c))}
    tr.appendChild(td)});t.appendChild(tr)});
  return t}
async function loadAll(){
  clearErr();
  try{
    const[ov,fu,ag,st,as,de,tr,rp,re,dly]=await Promise.all(
      ["/overview","/funnel","/agents","/strategies","/assets","/decisions","/trades","/reports","/replay","/daily"].map(j));
    // header
    badge("badge-data", ov.data==="REAL_PUBLIC_MARKET"?"REAL PUBLIC MARKET":"DEMO FIXTURE",
      ov.data==="REAL_PUBLIC_MARKET"?"b-real":"b-demo");
    badge("badge-campaign",(ov.campaign_id||"—")+" · "+(ov.campaign_state||"—"),"b-dim");
    document.getElementById("asof").textContent="as of "+new Date().toLocaleString();
    document.getElementById("f-camp").textContent=ov.campaign_id||"—";
    // overview cards
    const oc=document.getElementById("ov-cards");oc.textContent="";
    const prog=ov.campaign_progress||{};
    const cards=[
      ["Equity",fmt(ov.equity),""],
      ["Realized PnL",fmt(ov.realized_pnl),cls(ov.realized_pnl)],
      ["Unrealized PnL",fmt(ov.unrealized_pnl),cls(ov.unrealized_pnl)],
      ["PnL today",fmt(ov.pnl_today),cls(ov.pnl_today)],
      ["Max drawdown",ov.max_drawdown==null?"—":fmt(ov.max_drawdown,4),ov.max_drawdown?"neg":"flat"],
      ["Trades today",fmt(ov.trades_today,0)+(ov.trades_today_date?" ("+ov.trades_today_date+")":""),
        (ov.ge_3_target&&ov.ge_3_target.met)?"pos":"flat"],
      ["Open positions",fmt(ov.open_positions,0),""],
      ["Closed trades",fmt(ov.closed_trades,0),""],
      ["Campaign progress",(prog.valid_days??0)+" / "+(prog.target_days??7)+" valid days",""],
    ];
    cards.forEach(([k,v,c])=>{const d=$("div","card");d.appendChild($("div","k",k));
      const vv=$("div","v",v);if(c)vv.classList.add(c);d.appendChild(vv);oc.appendChild(d)});
    // daily chart + table
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
      ["realized PnL","max intraday DD"]));
    // funnel
    const fn=document.getElementById("fun");fn.textContent="";
    const counts=fu.counts||{};const conv=fu.conversions||{};const names=Object.keys(counts);
    const mx2=Math.max(1,...names.filter(n=>!["NO_TRADE","RISK_REJECT"].includes(n)).map(n=>counts[n]||0));
    names.forEach((n,i)=>{const row=$("div","frow");row.appendChild($("div",null,n));
      const bar=$("div","fbar");const sp=$("span");sp.style.width=(100*(counts[n]||0)/mx2)+"%";bar.appendChild(sp);row.appendChild(bar);
      row.appendChild($("div","c",counts[n]));
      const prev=names[i-1];row.appendChild($("div","p",prev?((conv[prev+"->"+n]!=null)?(100*conv[prev+"->"+n]).toFixed(1)+"%":"—"):""));
      fn.appendChild(row)});
    // agents
    const agl=document.getElementById("ag");agl.textContent="";
    (ag.items||[]).slice(-120).reverse().forEach(it=>{
      const li=$("li");const[cn,label]=chipFor(it.event);
      li.appendChild($("span","chip "+cn,label));
      li.appendChild($("span","meta",JSON.stringify(
        Object.fromEntries(Object.entries(it).filter(([k])=>k!=="event")))));
      agl.appendChild(li)});
    // strategies / assets
    document.getElementById("st").textContent="";
    document.getElementById("st").appendChild(table(
      ["strategy","evaluations","proposals","selected","trades","wins","losses","net PnL","expectancy","PF","sample"],
      (st.strategies||[]).map(s=>[s.strategy,s.evaluations,s.proposals,s.selected,s.trades,s.wins,s.losses,
        s.net_pnl==null?"—":fmt(s.net_pnl),s.expectancy==null?"—":fmt(s.expectancy,4),
        s.profit_factor==null?"—":fmt(s.profit_factor,3),s.sample]),
      ["net PnL","expectancy","PF"]));
    document.getElementById("as").textContent="";
    document.getElementById("as").appendChild(table(
      ["asset","proposals","selected","risk accepted","trades","net PnL","sample"],
      (as.assets||[]).map(a=>[a.asset,a.proposals,a.selected,a.risk_accepted,a.trades,
        a.net_pnl==null?"—":fmt(a.net_pnl),a.sample]),["net PnL"]));
    // decisions
    const deBox=document.getElementById("de");deBox.textContent="";
    (de.decisions||[]).slice(-40).reverse().forEach(d=>{
      const p=$("div","panel");p.style.marginBottom="8px";
      const h=$("div");h.style.display="flex";h.style.gap="10px";h.style.alignItems="baseline";
      const oc=$("span","chip "+(String(d.outcome).includes("SELECT")?"c-dec-sel":
        String(d.outcome).includes("NO_TRADE")?"c-dec-no":"c-dec-rej"),d.outcome||"—");
      h.appendChild(oc);
      h.appendChild($("span","meta","verifier: "+(d.verifier||"—")+" · winner: "+(d.winner||"—")+
        (d.decision_id?" · "+d.decision_id:"")));
      p.appendChild(h);
      const extra={alternatives:d.alternatives,dissent:d.dissent,revisions:d.revisions};
      const any=Object.values(extra).some(v=>v!=null&&(Array.isArray(v)?v.length:true));
      if(any){const dt=$("details");const sm=$("summary",null,"evidence / alternatives / dissent / revisions");
        const pr=$("pre");pr.textContent=JSON.stringify(extra,null,1);dt.appendChild(sm);dt.appendChild(pr);p.appendChild(dt)}
      deBox.appendChild(p)});
    const dm=de.campaign_aggregates||{};
    const agg=$("p","camp","campaign aggregates — selected: "+(dm.selected??"—")+
      " · rejected: "+(dm.rejected??"—")+" · no_trade: "+(dm.no_trade??"—")+
      " · verifier verified: "+(dm.verifier_verified??"—")+" · verifier rejected: "+(dm.verifier_rejected??"—"));
    deBox.prepend(agg);
    // trades
    document.getElementById("tr-open").textContent="";
    const op=tr.open_positions||[];
    document.getElementById("tr-open").appendChild(op.length?table(
      ["symbol","side","entry","qty","opened","decision"],
      op.map(o=>[o.symbol||o.asset,o.side,o.entry_price,o.quantity??o.qty,
        o.opened_at_ms?new Date(o.opened_at_ms).toISOString():o.opened_at,o.decision_id]),["entry"]):
      $("p","camp","no open positions"));
    document.getElementById("tr-closed").textContent="";
    const ct=tr.closed_trades||[];
    document.getElementById("tr-closed").appendChild(ct.length?table(
      ["symbol","side","entry","exit","exit reason","PnL","strategy","regime","decision"],
      ct.map(t=>[t.symbol||t.asset,t.side,t.entry_price,t.exit_price,t.exit_reason,t.pnl,
        t.strategy,t.regime,t.decision_id]),["PnL"]):$("p","camp","no closed trades"));
    // reports
    const rp=document.getElementById("rp");rp.textContent="";
    const ul=$("ul");ul.style.cssText="columns:2;gap:24px";
    (Array.isArray(rp)?rp:(rp.reports||[])).forEach(r=>{
      const li=$("li");const a=$("a",null,(r.campaign_id?r.campaign_id+"/":"")+r.name);
      a.href="/api/reports/content?path="+encodeURIComponent(r.path);
      a.setAttribute("download",r.name);li.appendChild(a);
      li.appendChild(document.createTextNode(" ("+r.bytes+" B)"));ul.appendChild(li)});
    rp.appendChild(ul);
    // replay
    const reEl=document.getElementById("re");reEl.textContent="";
    reEl.appendChild($("p",null,"RUN_REPLAY = "+re.RUN_REPLAY+" · run-level replay CLI: "+
      re.run_level_replay_cli));
    reEl.appendChild(table(["step","available","evidence"],
      (re.chain||[]).map(c=>[c.step,c.available?"available":"missing",c.evidence]),[]));
    reEl.appendChild($("p","camp",re.note||""));
  }catch(e){err(e)}
}
// tabs
document.getElementById("tabs").addEventListener("click",e=>{
  const a=e.target.closest("a");if(!a)return;
  document.querySelectorAll("nav a").forEach(x=>x.classList.remove("on"));a.classList.add("on");
  document.querySelectorAll("section").forEach(s=>s.classList.remove("on"));
  document.getElementById("s-"+a.dataset.t).classList.add("on")});
function route(){const h=(location.hash||"#overview").slice(1);
  const a=document.querySelector('nav a[data-t="'+h+'"]')||document.querySelector('nav a');
  if(a)a.click()}
window.addEventListener("hashchange",route);
document.getElementById("refresh").addEventListener("click",loadAll);
let timer=null;
document.getElementById("auto").addEventListener("change",e=>{
  if(e.target.checked){loadAll();timer=setInterval(loadAll,30000)}
  else if(timer){clearInterval(timer);timer=null}});
route();loadAll();
</script>
</body>
</html>
"""
