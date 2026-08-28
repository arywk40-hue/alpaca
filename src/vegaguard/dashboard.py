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
body{{font-family:ui-sans-serif,system-ui;background:#0b1020;color:#e6edf7;margin:0;padding:2rem;max-width:1100px}}
h1{{margin:0}} .sub{{color:#9fb0c9}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:1rem;margin:1.5rem 0}}
.card{{background:#141c32;border:1px solid #283754;border-radius:.65rem;padding:1rem}} .n{{font-size:1.7rem;font-weight:700}} pre{{white-space:pre-wrap;overflow:auto;font-size:.78rem}} .danger{{background:#8b1e2d;color:white}}
</style></head><body><h1>{safe_title}</h1><p class="sub">Paper-only decision trail and safety controls</p><p class="sub">Shadow and reprice P&amp;L are hypothetical evidence, never fills or realized P&amp;L.</p>
<section class="card"><h2>Agent controls</h2><p class="sub">Shadow scans cannot submit orders. A paper entry requires backend safety flags, a deliberate session arm, and an exact unexpired plan ID after every market, quote, liquidity, and risk gate passes.</p><p class="sub">Mutation controls require a backend bearer token in the request header; this page never contains that secret.</p><button id="start-shadow">Start Shadow Agent</button> <button id="stop-shadow">Stop Agent</button> <button id="start-simulation">Start Simulation Replay</button> <button id="arm-paper">Arm Paper Execution</button> <button id="disarm-paper">Disarm Paper Execution</button> <button id="emergency-stop" class="danger">Emergency Stop</button><p id="paper-lock" class="sub">Paper Execution: LOCKED by default</p><input id="plan-id" placeholder="Reviewed plan ID" aria-label="Reviewed plan ID"> <button id="submit-plan" disabled>Submit exact approved plan</button><pre id="agent">Loading…</pre></section>
<div id="cards" class="grid"></div><div class="grid"><section class="card"><h2>Shadow candidates</h2><pre id="candidates">Loading…</pre></section><section class="card"><h2>Risk-budget rejections</h2><pre id="risk-budget">Loading…</pre></section><section class="card"><h2>Hypothetical reprices (not fills)</h2><pre id="reprices">Loading…</pre></section><section class="card"><h2>Shadow audit</h2><pre id="shadows">Loading…</pre></section>
<section class="card"><h2>Scheduler heartbeat</h2><pre id="scheduler">Loading…</pre></section><section class="card"><h2>Journal timeline</h2><pre id="journal">Loading…</pre></section></div>
<script>
const refreshDashboard=()=>fetch('/dashboard/state').then(r=>r.json()).then(d=>{{
document.querySelector('#cards').innerHTML=[['Audit events',d.event_count],['Scheduler',d.scheduler.status],['Shadow opportunities',d.summary.shadow_opportunity_count],['Candidate observations',d.summary.shadow_candidate_count],['Exploration opportunities',d.summary.exploration_opportunity_count],['Exploration observations',d.summary.exploration_candidate_count],['Risk-budget rejections',d.summary.risk_budget_rejection_count],['HYPOTHETICAL reprices',d.summary.hypothetical_reprice_count],['Overdue reprices',d.summary.overdue_reprice_count],['Approved production plans',d.summary.approved_production_plan_count],['Approved exploration plans',d.summary.approved_exploration_plan_count],['Acknowledged PAPER ORDERS',d.summary.acknowledged_paper_order_count],['PAPER FILLS',d.summary.filled_paper_trade_count],['REALIZED PAPER P&L records',d.summary.realized_paper_trade_count],['Realized before unreported fees','$'+d.summary.realized_paper_pnl_before_fees],['Selected HYPOTHETICAL P&L','$'+d.summary.selected_hypothetical_pnl],['Exploration HYPOTHETICAL P&L','$'+d.summary.exploration_hypothetical_pnl],['Rejected-shadow HYPOTHETICAL P&L','$'+d.summary.rejected_shadow_hypothetical_pnl],['Selected − rejected-shadow HYPOTHETICAL','$'+d.summary.selected_minus_rejected_shadow_hypothetical_pnl],['Open paper unrealized P&L','$'+d.summary.open_position_unrealized_pnl]].map(x=>`<div class="card"><div class="sub">${{x[0]}}</div><div class="n">${{x[1]}}</div></div>`).join('');document.querySelector('#candidates').textContent=JSON.stringify(d.shadow_candidates,null,2);document.querySelector('#risk-budget').textContent=JSON.stringify(d.risk_budget_rejections,null,2);document.querySelector('#reprices').textContent=JSON.stringify(d.shadow_reprices,null,2);document.querySelector('#shadows').textContent=JSON.stringify(d.shadows,null,2);document.querySelector('#scheduler').textContent=JSON.stringify(d.scheduler,null,2);document.querySelector('#journal').textContent=JSON.stringify(d.journal,null,2);document.querySelector('#agent').textContent=JSON.stringify(d.agent,null,2);const paper=d.agent.paper_execution;document.querySelector('#paper-lock').textContent=paper.emergency_stop_active?'Paper Execution: EMERGENCY STOP ACTIVE':paper.locked?'Paper Execution: LOCKED — configuration and session arm required':'Paper Execution: ARMED for one exact unexpired plan attempt';document.querySelector('#submit-plan').disabled=paper.locked;}}).catch(e=>document.querySelector('#agent').textContent='Dashboard error: '+e);
const control=(path)=>fetch(path,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:path.includes('shadow/start')?JSON.stringify({{interval_seconds:900}}):undefined}}).then(refreshDashboard);
document.querySelector('#start-shadow').onclick=()=>control('/agent/shadow/start');document.querySelector('#stop-shadow').onclick=()=>control('/agent/shadow/stop');document.querySelector('#start-simulation').onclick=()=>control('/agent/simulation/start');
document.querySelector('#arm-paper').onclick=()=>{{const confirmation=window.prompt('Type ARM PAPER EXECUTION to arm one exact paper-plan attempt.');if(confirmation)fetch('/agent/paper/arm',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{confirmation}})}}).then(refreshDashboard);}};document.querySelector('#disarm-paper').onclick=()=>control('/agent/paper/disarm');document.querySelector('#emergency-stop').onclick=()=>{{if(window.confirm('Emergency stop disarms paper entry and stops backend workers. Continue?'))control('/agent/emergency-stop');}};
document.querySelector('#submit-plan').onclick=()=>{{const planId=document.querySelector('#plan-id').value.trim();if(planId)fetch('/agent/paper/submit-approved',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{plan_id:planId}})}}).then(refreshDashboard);}};
const eventStream=new EventSource('/events');eventStream.onmessage=()=>refreshDashboard();refreshDashboard();
</script>
</body></html>"""
