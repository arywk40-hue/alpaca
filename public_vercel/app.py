"""Isolated Vercel entry point for VegaGuard's read-only public replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

_BANNER = "SIMULATION REPLAY — READ-ONLY DEMO — NO ORDER EXECUTION"
_SNAPSHOT_PATH = Path(__file__).with_name("public_demo_snapshot.json")


def _load_safe_snapshot() -> dict[str, Any]:
    snapshot = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    safety = snapshot.get("safety", {})
    required = {
        "paper_only": True,
        "order_execution_enabled": False,
        "dry_run": True,
        "mcp_calls_enabled": False,
        "scheduler_available": False,
        "mutating_endpoints_available": False,
    }
    if snapshot.get("banner") != _BANNER or safety != required:
        raise RuntimeError("public demo snapshot failed its read-only safety contract")
    return snapshot


PUBLIC_SNAPSHOT = _load_safe_snapshot()

app = FastAPI(
    title="VegaGuard Public Replay",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def public_security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=300"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
        "img-src 'self' data:; frame-ancestors 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/", response_class=HTMLResponse)
def public_dashboard() -> str:
    return PUBLIC_DEMO_HTML


@app.get("/healthz")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": "simulation_replay",
        "read_only": True,
        "order_execution_enabled": False,
        "persistent_scheduler": False,
    }


@app.get("/demo/state", response_class=JSONResponse)
def demo_state() -> dict[str, Any]:
    return PUBLIC_SNAPSHOT


PUBLIC_DEMO_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="description" content="VegaGuard's sanitized, read-only paper-options replay.">
  <title>VegaGuard · Public Replay</title>
  <style>
    :root { color-scheme: dark; --bg:#080b10; --panel:#10151d; --line:#26303d;
      --text:#edf2f7; --muted:#8d99a8; --green:#62d69b; --amber:#f5c86b;
      --red:#ef7e86; --blue:#75a9ff; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; background:radial-gradient(circle at 15% 0,#17233a 0,
      var(--bg) 42%); color:var(--text); font:14px/1.5 Inter,ui-sans-serif,system-ui,sans-serif; }
    .banner { position:sticky; top:0; z-index:4; padding:12px 20px; text-align:center;
      color:#141006; background:var(--amber); font-weight:900; letter-spacing:.08em; }
    main { width:min(1180px,calc(100% - 32px)); margin:0 auto; padding:42px 0 56px; }
    header { display:flex; justify-content:space-between; align-items:flex-end; gap:24px;
      margin-bottom:26px; }
    .eyebrow,.label { color:var(--muted); font-size:11px; font-weight:800;
      letter-spacing:.12em; text-transform:uppercase; }
    h1 { margin:6px 0 8px; font-size:clamp(38px,7vw,74px); line-height:.95;
      letter-spacing:-.055em; }
    .sub { max-width:690px; margin:0; color:#bac4d0; font-size:16px; }
    .pills { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; }
    .pill { padding:7px 10px; border:1px solid var(--line); border-radius:999px;
      font-size:11px; font-weight:800; letter-spacing:.06em; }
    .pill.safe { color:var(--green); border-color:#2b7256; }
    .pill.replay { color:var(--amber); border-color:#7b6332; }
    .grid { display:grid; grid-template-columns:repeat(4,1fr); border:1px solid var(--line);
      background:var(--panel); }
    .metric { min-height:128px; padding:18px; border-right:1px solid var(--line); }
    .metric:last-child { border-right:0; }
    .metric strong { display:block; margin-top:17px; font-size:28px; letter-spacing:-.03em; }
    .metric small { color:var(--muted); }
    .positive { color:var(--green); }
    .unknown { color:var(--amber); }
    .two-col { display:grid; grid-template-columns:1.2fr .8fr; gap:16px; margin-top:16px; }
    .panel { padding:20px; border:1px solid var(--line); background:var(--panel); }
    .panel-head { display:flex; justify-content:space-between; gap:16px; align-items:center;
      margin-bottom:17px; }
    h2 { margin:0; font-size:15px; }
    .status { color:var(--green); font-size:11px; font-weight:850; letter-spacing:.08em; }
    .steps { display:grid; grid-template-columns:repeat(7,1fr); border:1px solid var(--line); }
    .step { min-height:76px; padding:12px 9px; border-right:1px solid var(--line); }
    .step:last-child { border-right:0; }
    .step i { display:block; width:7px; height:7px; margin-bottom:14px; border-radius:50%;
      background:var(--green); box-shadow:0 0 0 4px #62d69b14; }
    .step span { color:#cbd4de; font-size:9px; font-weight:800; letter-spacing:.06em; }
    .disclosure { margin:14px 0 0; color:var(--muted); font-size:12px; }
    .timeline { list-style:none; margin:0; padding:0; }
    .timeline li { display:grid; grid-template-columns:12px 1fr auto; gap:10px; padding:11px 0;
      border-top:1px solid var(--line); opacity:.38; transition:opacity .35s ease; }
    .timeline li.visible { opacity:1; }
    .timeline i { width:7px; height:7px; margin-top:6px; border-radius:50%; background:var(--blue); }
    .timeline strong { display:block; font-size:12px; }
    .timeline p,.timeline time { margin:2px 0 0; color:var(--muted); font-size:10px; }
    .decision-grid,.reprice-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
    .decision,.reprice { padding:14px; border:1px solid var(--line); background:#0c1118; }
    .decision.approved { border-color:#2b7256; }
    .decision.rejected { border-color:#744049; }
    .decision b,.reprice b { display:block; margin:7px 0; font-size:14px; }
    .decision p,.reprice p { margin:0; color:var(--muted); font-size:11px; }
    .section { margin-top:16px; }
    footer { display:flex; justify-content:space-between; gap:20px; padding-top:22px;
      color:var(--muted); font-size:11px; }
    code { color:#c8d8ee; }
    @media(max-width:860px) { header{align-items:flex-start;flex-direction:column}.pills{justify-content:flex-start}
      .grid{grid-template-columns:repeat(2,1fr)}.metric:nth-child(2){border-right:0}
      .metric:nth-child(-n+2){border-bottom:1px solid var(--line)}.two-col{grid-template-columns:1fr}
      .steps{grid-template-columns:repeat(2,1fr)}.decision-grid,.reprice-grid{grid-template-columns:1fr} }
  </style>
</head>
<body>
  <div class="banner">SIMULATION REPLAY — READ-ONLY DEMO — NO ORDER EXECUTION</div>
  <main>
    <header>
      <div>
        <div class="eyebrow">VegaGuard / public evidence replay</div>
        <h1>Evidence before execution.</h1>
        <p class="sub">A sanitized replay of one completed Alpaca paper-options lifecycle,
          alongside decisions the agent rejected. Nothing on this page is live or executable.</p>
      </div>
      <div class="pills">
        <span class="pill safe">PAPER EVIDENCE</span>
        <span class="pill safe">READ ONLY</span>
        <span class="pill replay">NO PERSISTENT SCHEDULER</span>
      </div>
    </header>

    <section class="grid" aria-label="Paper lifecycle performance">
      <article class="metric"><div class="label">Completed lifecycle</div><strong>1</strong>
        <small>one two-leg IWM spread</small></article>
      <article class="metric"><div class="label">Gross paper P&amp;L</div>
        <strong id="gross-pnl" class="positive">+$2.00</strong><small>fill to fill</small></article>
      <article class="metric"><div class="label">Fees</div><strong class="unknown">UNKNOWN</strong>
        <small>not reported by Alpaca</small></article>
      <article class="metric"><div class="label">Net P&amp;L</div><strong class="unknown">UNKNOWN</strong>
        <small>not inferred without fees</small></article>
    </section>

    <section class="two-col">
      <article class="panel">
        <div class="panel-head"><h2>Replayed paper lifecycle</h2>
          <span class="status">COMPLETE · SANITIZED</span></div>
        <div class="steps">
          <div class="step"><i></i><span>APPROVED</span></div>
          <div class="step"><i></i><span>SUBMITTED</span></div>
          <div class="step"><i></i><span>ACKNOWLEDGED</span></div>
          <div class="step"><i></i><span>FILLED</span></div>
          <div class="step"><i></i><span>MONITORED</span></div>
          <div class="step"><i></i><span>EXIT FILLED</span></div>
          <div class="step"><i></i><span>P&amp;L RECONCILED</span></div>
        </div>
        <p class="disclosure">IWM Sep 25 292.5/284 bear-put spread · one contract ·
          $2.62 debit → $2.64 credit. Exit was operator-authorized for lifecycle completion.</p>
      </article>
      <article class="panel">
        <div class="panel-head"><h2>Browser replay</h2><span class="status">LOOPING LOCALLY</span></div>
        <ol id="timeline" class="timeline"><li class="visible"><i></i><div>
          <strong>Loading sanitized events</strong><p>No broker connection is used.</p></div>
          <time>REPLAY</time></li></ol>
      </article>
    </section>

    <section class="panel section">
      <div class="panel-head"><h2>Agent decisions</h2>
        <span class="label">approved and rejected evidence</span></div>
      <div id="decisions" class="decision-grid"></div>
    </section>

    <section class="panel section">
      <div class="panel-head"><h2>Shadow repricing</h2>
        <span class="label">hypothetical · never paper fills</span></div>
      <div id="reprices" class="reprice-grid"></div>
    </section>

    <footer><span>Hosted mode has no Alpaca connection, MCP calls, scheduler, journal,
      operator controls or mutation routes.</span><span><code>production threshold = 70</code></span></footer>
  </main>
  <script>
    const money=value=>value===null||value===undefined?'UNKNOWN':
      (Number(value)>=0?'+$':'−$')+Math.abs(Number(value)).toFixed(2);
    const esc=value=>String(value??'').replace(/[&<>"']/g,c=>
      ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    let events=[]; let visibleCount=1;
    function renderTimeline(){
      const shown=events.slice(0,visibleCount);
      document.querySelector('#timeline').innerHTML=shown.map(event=>
        `<li class="visible"><i></i><div><strong>${esc(event.title)}</strong>`+
        `<p>${esc(event.detail)}</p></div><time>${esc(event.stage.toUpperCase())}</time></li>`
      ).join('');
    }
    function render(data){
      document.querySelector('#gross-pnl').textContent=money(data.performance.gross_realized_pnl_usd);
      events=data.workflow_events||[]; visibleCount=Math.min(Math.max(visibleCount,1),events.length);
      renderTimeline();
      document.querySelector('#decisions').innerHTML=data.decisions.map(item=>
        `<article class="decision ${item.decision.startsWith('approved')?'approved':'rejected'}">`+
        `<span class="label">${esc(item.underlying)} · score ${esc(item.score)}</span>`+
        `<b>${esc(item.decision.replaceAll('_',' '))}</b><p>${esc(item.reason)}</p></article>`
      ).join('');
      document.querySelector('#reprices').innerHTML=data.shadow_reprices.map(item=>
        `<article class="reprice"><span class="label">${esc(item.horizon_minutes)} MINUTES</span>`+
        `<b>${esc(item.status.toUpperCase())}</b><p>${item.status==='priced'?
          esc(money(item.net_hypothetical_pnl_usd)+' hypothetical'):esc(item.reason)}</p></article>`
      ).join('');
    }
    async function load(){
      const response=await fetch('/demo/state',{headers:{Accept:'application/json'}});
      if(!response.ok) throw new Error('Replay unavailable');
      render(await response.json());
    }
    load().catch(()=>document.querySelector('#timeline').innerHTML=
      '<li class="visible"><i></i><div><strong>Replay unavailable</strong><p>Refresh to retry.</p></div></li>');
    setInterval(()=>{if(events.length){visibleCount=visibleCount>=events.length?1:visibleCount+1;renderTimeline();}},1800);
    setInterval(()=>load().catch(()=>{}),30000);
  </script>
</body>
</html>"""
