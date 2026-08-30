"""Dependency-free dashboard read model and one-page FastAPI presentation."""

from __future__ import annotations

from html import escape
from typing import Any

from .journal import DecisionJournal


def dashboard_state(journal: DecisionJournal, *, limit: int = 20) -> dict[str, Any]:
    shadows = journal.shadows(limit)
    candidates = journal.shadow_candidates(limit)
    reprices = journal.shadow_reprices(limit * 3)
    risk_budget_rejections = journal.risk_budget_rejections(limit)
    thesis_explanations = journal.thesis_explanations(limit)
    scheduler = journal.scheduler_status()
    session_report = journal.shadow_session_report()
    outcome_metrics = session_report["hypothetical_pnl_by_outcome_bucket"]
    selected_hypothetical = float(outcome_metrics["selected"]["net_hypothetical_pnl"])
    rejected_shadow_hypothetical = float(outcome_metrics["shadow"]["net_hypothetical_pnl"])
    exploration_hypothetical = float(outcome_metrics["exploration"]["net_hypothetical_pnl"])
    overdue_reprice_count = sum(
        str((candidate.get("reprice_status") or {}).get("status", "")).startswith("overdue_")
        for candidate in candidates
    )
    completed = [shadow for shadow in shadows if shadow["closed_at"]]
    exploration_shadows = [
        shadow
        for shadow in shadows
        if shadow.get("trade_mode") == "exploration"
        or shadow.get("selected_plan", {}).get("trade_mode") == "exploration"
    ]
    exploration_candidates = [
        candidate for candidate in candidates if candidate.get("trade_mode") == "exploration"
    ]
    opportunity_count = len(
        {str(candidate.get("opportunity_id") or candidate["id"]) for candidate in candidates}
    )
    exploration_opportunity_count = len(
        {
            str(candidate.get("opportunity_id") or candidate["id"])
            for candidate in exploration_candidates
        }
    )
    events = journal.latest(max(limit, 200))
    completed_paper_trades = journal.complete_trade_evidence()
    acknowledged_order_ids: set[str] = set()
    for event in events:
        if (
            event.get("event") == "order_acknowledged"
            and event.get("plan")
            and not event["plan"].get("parent_client_order_id")
        ):
            acknowledged_order_ids.add(str(event["plan"]["client_order_id"]))
        payload = event.get("payload") or {}
        if (
            event.get("event") == "order_lifecycle_transition"
            and payload.get("status") in {"accepted", "partially_filled", "filled", "submitted"}
            and payload.get("client_order_id")
        ):
            acknowledged_order_ids.add(str(payload["client_order_id"]))
    filled_trade_ids = {
        str((event.get("plan") or {}).get("client_order_id"))
        for event in events
        if event.get("event") == "position_entry_filled"
        and event.get("plan")
        and not (event["plan"].get("parent_client_order_id"))
    }
    latest_marks: dict[str, float] = {}
    for event in reversed(events):
        if event.get("event") != "position_mark":
            continue
        client_order_id = (event.get("plan") or {}).get("client_order_id")
        value = (event.get("payload") or {}).get("unrealized_pnl")
        if client_order_id and value is not None:
            latest_marks[str(client_order_id)] = float(value)
    return {
        "event_count": journal.ledger.event_count(),
        "journal": events[:limit],
        "shadows": shadows,
        "shadow_candidates": candidates,
        "shadow_reprices": reprices,
        "risk_budget_rejections": risk_budget_rejections,
        "thesis_explanations": thesis_explanations,
        "latest_thesis_explanation": thesis_explanations[0] if thesis_explanations else None,
        "scheduler": scheduler,
        "summary": {
            "approved_production_plan_count": len(shadows) - len(exploration_shadows),
            "approved_exploration_plan_count": len(exploration_shadows),
            "shadow_candidate_count": len(candidates),
            "shadow_opportunity_count": opportunity_count,
            "exploration_candidate_count": len(exploration_candidates),
            "exploration_opportunity_count": exploration_opportunity_count,
            "acknowledged_paper_order_count": len(acknowledged_order_ids),
            "filled_paper_trade_count": len(filled_trade_ids),
            "realized_paper_trade_count": len(completed_paper_trades),
            "realized_paper_pnl_before_fees": round(
                sum(
                    float(trade.get("realized_pnl_before_fees") or 0)
                    for trade in completed_paper_trades
                ),
                2,
            ),
            "realized_paper_pnl_after_fees": (
                round(
                    sum(
                        float(trade["realized_pnl_after_fees"]) for trade in completed_paper_trades
                    ),
                    2,
                )
                if completed_paper_trades
                and all(
                    trade.get("realized_pnl_after_fees") is not None
                    for trade in completed_paper_trades
                )
                else None
            ),
            "hypothetical_reprice_count": len(reprices),
            "overdue_reprice_count": overdue_reprice_count,
            "risk_budget_rejection_count": len(risk_budget_rejections),
            "completed_shadow_audits": len(completed),
            "selected_minus_shadow_pnl": round(
                sum(
                    float(shadow["selected_net_pnl"] or 0) - float(shadow["shadow_net_pnl"] or 0)
                    for shadow in completed
                ),
                2,
            ),
            "selected_hypothetical_pnl": round(selected_hypothetical, 2),
            "exploration_hypothetical_pnl": round(exploration_hypothetical, 2),
            "rejected_shadow_hypothetical_pnl": round(rejected_shadow_hypothetical, 2),
            "selected_minus_rejected_shadow_hypothetical_pnl": round(
                selected_hypothetical - rejected_shadow_hypothetical, 2
            ),
            "open_position_unrealized_pnl": round(sum(latest_marks.values()), 2),
        },
        "shadow_session_report": session_report,
        "completed_paper_trades": completed_paper_trades,
        "open_position_marks": [
            {"client_order_id": client_order_id, "unrealized_pnl": value}
            for client_order_id, value in sorted(latest_marks.items())
        ],
    }


def dashboard_html(title: str = "VegaGuard") -> str:
    safe_title = escape(title)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title}</title><style>
:root{{color-scheme:dark;--bg:#080d1c;--panel:#111a30;--panel-2:#17233d;--line:#2a3a5c;--text:#edf4ff;--muted:#9fb0ca;--green:#55e6a5;--amber:#ffd166;--red:#ff6b7a;--blue:#7db7ff}}
*{{box-sizing:border-box}}body{{font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;background:radial-gradient(circle at 10% 0%,#17254a 0,#080d1c 42%);color:var(--text);margin:0;padding:2rem;max-width:1280px;margin-inline:auto}}
h1,h2,h3,p{{margin-top:0}}h1{{font-size:clamp(2rem,4vw,3.6rem);letter-spacing:-.05em;margin-bottom:.35rem}}.sub{{color:var(--muted);line-height:1.5}}.eyebrow{{color:var(--blue);font-size:.75rem;font-weight:800;letter-spacing:.18em}}.hero{{display:flex;align-items:flex-start;justify-content:space-between;gap:1.5rem;margin-bottom:1.5rem}}.hero-copy{{max-width:760px}}.badges{{display:flex;gap:.6rem;flex-wrap:wrap;justify-content:flex-end}}.badge{{border-radius:999px;padding:.55rem .8rem;font-size:.72rem;font-weight:900;letter-spacing:.1em;white-space:nowrap}}.paper{{background:#123f38;color:var(--green);border:1px solid #267963}}.fills{{background:#4b2630;color:#ffd0d6;border:1px solid #9b4555}}.live{{background:#19355c;color:var(--blue);border:1px solid #3d6ea8}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:1rem;margin:1rem 0 1.5rem}}.card{{background:linear-gradient(145deg,var(--panel),#0e1629);border:1px solid var(--line);border-radius:1rem;padding:1.15rem;box-shadow:0 10px 30px #0003}}.card h2{{font-size:1rem;margin-bottom:.8rem}}.metric{{min-height:116px;position:relative;overflow:hidden}}.metric:after{{content:"";position:absolute;inset:auto -25px -55px auto;width:120px;height:120px;border-radius:50%;background:#7db7ff12}}.metric .label{{color:var(--muted);font-size:.72rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}}.metric .n{{font-size:1.65rem;font-weight:850;margin-top:.5rem}}.metric .hint{{color:var(--muted);font-size:.78rem;margin-top:.35rem}}.metric.ok{{border-color:#287c61}}.metric.warn{{border-color:#886c2d}}.metric.danger{{border-color:#914451}}.section-head{{display:flex;align-items:center;justify-content:space-between;gap:1rem}}.status-badge{{border:1px solid var(--line);border-radius:999px;padding:.35rem .65rem;font-size:.7rem;font-weight:900;letter-spacing:.08em}}.status-badge.running,.status-badge.waiting{{color:var(--green);border-color:#287c61;background:#123f3838}}.status-badge.error,.status-badge.stale{{color:var(--red);border-color:#914451;background:#4b263033}}.status-badge.stopped,.status-badge.never_started{{color:var(--muted)}}.agent-facts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.7rem;margin:1rem 0}}.fact{{background:var(--panel-2);border-radius:.7rem;padding:.65rem}}.fact strong{{display:block;font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}}.fact span{{display:block;margin-top:.25rem;font-size:.82rem;word-break:break-word}}
.operator{{border-color:#466da9}}.operator-grid{{display:grid;grid-template-columns:minmax(230px,1fr) auto auto;gap:.7rem;align-items:end}}.field{{display:flex;flex-direction:column;gap:.35rem}}.field label{{font-size:.75rem;color:var(--muted);font-weight:700}}.field input,#plan-id{{width:100%;background:#0a1225;border:1px solid var(--line);border-radius:.55rem;color:var(--text);padding:.65rem .75rem;min-height:2.4rem}}button{{background:#23385d;color:var(--text);border:1px solid #43679c;border-radius:.55rem;padding:.65rem .85rem;font-weight:750;cursor:pointer;min-height:2.4rem}}button:hover{{filter:brightness(1.18)}}button:disabled{{opacity:.4;cursor:not-allowed}}button.danger{{background:#6f2635;border-color:#a74456;color:#fff}}.auth-status{{display:inline-flex;margin-top:.85rem;border-radius:.5rem;padding:.45rem .65rem;font-size:.76rem;font-weight:800}}.auth-status.locked{{color:var(--muted);background:#28344b}}.auth-status.ready{{color:var(--amber);background:#5e4d1f}}.auth-status.ok{{color:var(--green);background:#123f38}}.auth-status.error{{color:#ffd0d6;background:#4b2630}}.auth-status.warn{{color:var(--amber);background:#5e4d1f}}.plan-row{{display:grid;grid-template-columns:minmax(230px,1fr) auto;gap:.7rem;margin-top:1rem;align-items:end}}
pre{{white-space:pre-wrap;overflow:auto;font-size:.76rem;color:#c9d7ed;line-height:1.45;background:#0a1221;border-radius:.65rem;padding:.8rem;max-height:360px}}.timeline{{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:.8rem;max-height:470px;overflow:auto}}.timeline li{{display:grid;grid-template-columns:18px 1fr;gap:.65rem;position:relative;padding:.2rem 0}}.timeline li:not(:last-child):after{{content:"";position:absolute;left:8px;top:20px;bottom:-14px;width:1px;background:var(--line)}}.timeline-dot{{display:block;width:11px;height:11px;margin-top:.3rem;border-radius:50%;background:#4c6c9c;border:2px solid #8bb5ee}}.timeline li.latest .timeline-dot{{background:var(--green);border-color:var(--green);box-shadow:0 0 0 0 #55e6a577;animation:pulse 1.8s infinite}}.timeline strong{{font-size:.82rem}}.timeline time{{display:block;color:var(--muted);font-size:.7rem;margin-top:.12rem}}.timeline p{{color:#c5d2e7;font-size:.76rem;margin:.25rem 0 0}}.empty{{color:var(--muted);padding:.5rem 0}}@keyframes pulse{{70%{{box-shadow:0 0 0 8px #55e6a500}}100%{{box-shadow:0 0 0 0 #55e6a500}}}}
@media (max-width:720px){{body{{padding:1rem}}.hero{{flex-direction:column}}.badges{{justify-content:flex-start}}.operator-grid,.plan-row{{grid-template-columns:1fr}}button{{width:100%}}}}
</style></head><body><header class="hero"><div class="hero-copy"><div class="eyebrow">VEGAGUARD // OPERATOR CONSOLE</div><h1>Evidence before execution.</h1><p class="sub">A paper-only decision trail with explicit safety gates, hypothetical shadow evidence, and auditable lifecycle state. Shadow and reprice P&amp;L are hypothetical evidence, never fills or realized P&amp;L.</p></div><div class="badges"><span class="badge paper">PAPER ONLY</span><span id="fill-badge" class="badge fills">NO FILLS YET</span><span class="badge live">LIVE SSE</span></div></header>
<section class="card"><div class="section-head"><h2>Agent status</h2><span id="agent-status-badge" class="status-badge stopped">STOPPED</span></div><div class="agent-facts"><div class="fact"><strong>Last cycle</strong><span id="last-cycle">—</span></div><div class="fact"><strong>Next cycle</strong><span id="next-cycle">—</span></div><div class="fact"><strong>Market</strong><span id="market-state">—</span></div><div class="fact"><strong>Last error</strong><span id="last-error">None</span></div></div><pre id="agent">Loading…</pre></section>
<section class="card operator"><div class="section-head"><div><h2>Local operator mode</h2><p class="sub">Enter the backend bearer token manually. It is held only in this tab's sessionStorage/memory, cleared from the input after saving, and never embedded in dashboard HTML.</p></div><span id="auth-status" class="auth-status locked">LOCKED — no operator token in this tab</span></div><div class="operator-grid"><div class="field"><label for="operator-token">Operator bearer token</label><input id="operator-token" type="password" autocomplete="off" spellcheck="false" placeholder="Paste token locally; it will not be displayed"></div><button id="save-token">Authorize operator</button><button id="clear-token">Forget token</button></div></section>
<section class="card"><div class="section-head"><h2>Agent controls</h2><span class="sub">Every button is bearer-protected</span></div><p class="sub">Shadow scans cannot submit orders. A paper entry still requires backend safety flags, a deliberate session arm, and an exact unexpired plan ID after every market, quote, liquidity, and risk gate passes.</p><div class="grid"><button id="start-shadow">Start Shadow Agent</button><button id="stop-shadow">Stop Agent</button><button id="start-simulation">Start Simulation Replay</button><button id="arm-paper">Arm Paper Execution</button><button id="disarm-paper">Disarm Paper Execution</button><button id="emergency-stop" class="danger">Emergency Stop</button></div><p id="paper-lock" class="sub">Paper Execution: LOCKED by default</p><div class="plan-row"><div class="field"><label for="plan-id">Reviewed plan ID</label><input id="plan-id" placeholder="Exact unexpired plan ID" aria-label="Reviewed plan ID"></div><button id="submit-plan" disabled>Submit exact approved plan</button></div></section>
<div id="cards" class="grid"></div><p class="sub">Approved exploration plans and approved production plans remain separate from acknowledged orders, fills, and <span>REALIZED P&amp;L</span>.</p><section class="card"><div class="section-head"><h2>Live event timeline</h2><span class="sub">SSE → durable journal</span></div><ol id="timeline" class="timeline"><li class="empty">Waiting for the first event…</li></ol></section><div class="grid"><section class="card"><h2>Shadow candidates</h2><pre id="candidates">Loading…</pre></section><section class="card"><h2>Risk-budget rejections</h2><pre id="risk-budget">Loading…</pre></section><section class="card"><h2>Hypothetical reprices (not fills)</h2><pre id="reprices">Loading…</pre></section><section class="card"><h2>Shadow audit</h2><pre id="shadows">Loading…</pre></section><section class="card"><h2>Scheduler heartbeat</h2><pre id="scheduler">Loading…</pre></section><section class="card"><h2>Journal payloads</h2><pre id="journal">Loading…</pre></section></div>
<section class="card"><div class="section-head"><h2>Trade Thesis &amp; Risk Explainer</h2><span class="badge live">ADVISORY ONLY</span></div><p class="sub">Summarizes validated scanner, spread, and risk facts. This explanation cannot change score, threshold, legs, quantity, risk approval, or execution.</p><pre id="thesis-explanation">Waiting for a thesis explanation…</pre></section>
<script>
const operatorTokenKey='vegaguard.dashboard.operator_token';let operatorTokenMemory='';
const readOperatorToken=()=>{{if(operatorTokenMemory)return operatorTokenMemory;try{{return sessionStorage.getItem(operatorTokenKey)||'';}}catch(_error){{return '';}}}};
const setAuthStatus=(message,kind)=>{{const node=document.querySelector('#auth-status');node.textContent=message;node.className='auth-status '+kind;}};
const saveOperatorToken=()=>{{const input=document.querySelector('#operator-token');const value=input.value.trim();if(!value){{setAuthStatus('LOCKED — enter a token first','locked');return;}}operatorTokenMemory=value;try{{sessionStorage.setItem(operatorTokenKey,value);}}catch(_error){{}}input.value='';setAuthStatus('TOKEN STORED — protected action will verify it','ready');}};
const clearOperatorToken=()=>{{operatorTokenMemory='';try{{sessionStorage.removeItem(operatorTokenKey);}}catch(_error){{}}document.querySelector('#operator-token').value='';setAuthStatus('LOCKED — no operator token in this tab','locked');}};
const escapeHtml=value=>String(value??'').replace(/[&<>'"]/g,char=>({{'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}}[char]));
const displayTime=value=>value?new Date(value).toLocaleTimeString():'—';const displayMoney=value=>value===null||value===undefined?'—':'$'+Number(value).toFixed(2);
const renderTimeline=events=>{{const node=document.querySelector('#timeline');if(!events||!events.length){{node.innerHTML='<li class="empty">Waiting for the first event…</li>';return;}}node.innerHTML=events.slice(0,24).map((event,index)=>{{const payload=event.payload||{{}};const detail=payload.reason||payload.status||payload.classification||payload.provider_status||'';return `<li class="${{index===0?'latest':''}}"><span class="timeline-dot"></span><div><strong>${{escapeHtml(event.event||'event')}}</strong><time>${{escapeHtml(event.timestamp||'')}}</time><p>${{escapeHtml(detail)}}</p></div></li>`;}}).join('');}};
const refreshDashboard=()=>fetch('/dashboard/state').then(response=>response.json()).then(d=>{{const summary=d.summary;const scheduler=d.scheduler||{{}};const paper=d.agent.paper_execution;const schedulerStatus=String(scheduler.status||'unknown');const cards=[['SIMULATION',String(d.agent.simulation.status||'idle').toUpperCase(),d.agent.simulation.mode||'fixture replay only'],['HYPOTHETICAL SHADOW RESULTS',summary.hypothetical_reprice_count+' reprices',displayMoney(summary.selected_hypothetical_pnl)+' selected evidence'],['APPROVED PLANS',summary.approved_production_plan_count+summary.approved_exploration_plan_count,'production + exploration'],['ACKNOWLEDGED ORDERS',summary.acknowledged_paper_order_count,'Alpaca acknowledgement only'],['FILLS',summary.filled_paper_trade_count,'paper fills only'],['REALIZED P&L',summary.realized_paper_trade_count+' records',displayMoney(summary.realized_paper_pnl_after_fees)]];document.querySelector('#cards').innerHTML=cards.map(item=>`<div class="card metric"><div class="label">${{escapeHtml(item[0])}}</div><div class="n">${{escapeHtml(item[1])}}</div><div class="hint">${{escapeHtml(item[2])}}</div></div>`).join('');document.querySelector('#fill-badge').textContent=summary.filled_paper_trade_count?summary.filled_paper_trade_count+' PAPER FILLS':'NO FILLS YET';document.querySelector('#last-cycle').textContent=displayTime(scheduler.last_cycle_completed_at);document.querySelector('#next-cycle').textContent=displayTime(scheduler.next_run_at);document.querySelector('#market-state').textContent=scheduler.market_open===true?'OPEN':scheduler.market_open===false?'CLOSED':'UNKNOWN';document.querySelector('#last-error').textContent=scheduler.last_error||'None';const statusNode=document.querySelector('#agent-status-badge');statusNode.textContent=schedulerStatus.toUpperCase();statusNode.className='status-badge '+schedulerStatus;document.querySelector('#candidates').textContent=JSON.stringify(d.shadow_candidates,null,2);document.querySelector('#risk-budget').textContent=JSON.stringify(d.risk_budget_rejections,null,2);document.querySelector('#reprices').textContent=JSON.stringify(d.shadow_reprices,null,2);document.querySelector('#shadows').textContent=JSON.stringify(d.shadows,null,2);document.querySelector('#scheduler').textContent=JSON.stringify(scheduler,null,2);document.querySelector('#journal').textContent=JSON.stringify(d.journal,null,2);document.querySelector('#agent').textContent=JSON.stringify(d.agent,null,2);document.querySelector('#thesis-explanation').textContent=JSON.stringify(d.latest_thesis_explanation||{{}},null,2);document.querySelector('#paper-lock').textContent=paper.emergency_stop_active?'Paper Execution: EMERGENCY STOP ACTIVE':paper.locked?'Paper Execution: LOCKED by default — configuration and session arm required':'Paper Execution: ARMED for one exact unexpired plan attempt';document.querySelector('#submit-plan').disabled=paper.locked;renderTimeline(d.journal);}}).catch(()=>document.querySelector('#agent').textContent='Dashboard read unavailable');
const mutation=(path,init={{}})=>{{const token=readOperatorToken();if(!token){{setAuthStatus('LOCKED — enter a token before mutating','locked');return Promise.resolve(null);}}const headers={{'Authorization':'Bearer '+token}};if(init.body)headers['Content-Type']='application/json';return fetch(path,Object.assign({{}},init,{{method:'POST',headers}})).then(response=>{{if(response.status===401)setAuthStatus('UNAUTHORIZED — token rejected','error');else if(response.ok)setAuthStatus('AUTHORIZED — protected action accepted','ok');else setAuthStatus('AUTHORIZED — safety gate returned '+response.status,'warn');return response;}}).catch(()=>{{setAuthStatus('AUTHORIZATION REQUEST FAILED','error');return null;}}).then(()=>refreshDashboard());}};
const control=(path,body)=>mutation(path,body?{{body:JSON.stringify(body)}}:{{}});
document.querySelector('#save-token').onclick=saveOperatorToken;document.querySelector('#clear-token').onclick=clearOperatorToken;document.querySelector('#start-shadow').onclick=()=>control('/agent/shadow/start',{{interval_seconds:900}});document.querySelector('#stop-shadow').onclick=()=>control('/agent/shadow/stop');document.querySelector('#start-simulation').onclick=()=>control('/agent/simulation/start');document.querySelector('#arm-paper').onclick=()=>{{const confirmation=window.prompt('Type ARM PAPER EXECUTION to arm one exact paper-plan attempt.');if(confirmation)control('/agent/paper/arm',{{confirmation}});}};document.querySelector('#disarm-paper').onclick=()=>control('/agent/paper/disarm');document.querySelector('#emergency-stop').onclick=()=>{{if(window.confirm('Emergency stop disarms paper entry and stops backend workers. Continue?'))control('/agent/emergency-stop');}};
document.querySelector('#submit-plan').onclick=()=>{{const planId=document.querySelector('#plan-id').value.trim();if(planId)control('/agent/paper/submit-approved',{{plan_id:planId}});}};if(readOperatorToken())setAuthStatus('TOKEN AVAILABLE — protected action will verify it','ready');const eventStream=new EventSource('/events');eventStream.onmessage=()=>refreshDashboard();refreshDashboard();
</script>
</body></html>"""
