"""Dependency-free dashboard read model and one-page FastAPI presentation."""

from __future__ import annotations

from html import escape
from typing import Any

from .journal import DecisionJournal


def dashboard_state(journal: DecisionJournal, *, limit: int = 20) -> dict[str, Any]:
    shadows = journal.shadows(limit)
    completed = [shadow for shadow in shadows if shadow["closed_at"]]
    return {
        "event_count": journal.ledger.event_count(),
        "journal": journal.latest(limit),
        "shadows": shadows,
        "summary": {
            "shadow_trade_count": len(shadows),
            "completed_shadow_audits": len(completed),
            "selected_minus_shadow_pnl": round(
                sum(
                    float(shadow["selected_net_pnl"] or 0) - float(shadow["shadow_net_pnl"] or 0)
                    for shadow in completed
                ),
                2,
            ),
        },
    }


def dashboard_html(title: str = "VegaGuard") -> str:
    safe_title = escape(title)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title}</title><style>
body{{font-family:ui-sans-serif,system-ui;background:#0b1020;color:#e6edf7;margin:0;padding:2rem;max-width:1100px}}
h1{{margin:0}} .sub{{color:#9fb0c9}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:1rem;margin:1.5rem 0}}
.card{{background:#141c32;border:1px solid #283754;border-radius:.65rem;padding:1rem}} .n{{font-size:1.7rem;font-weight:700}} pre{{white-space:pre-wrap;overflow:auto;font-size:.78rem}}
</style></head><body><h1>{safe_title}</h1><p class="sub">Paper-only decision trail · no live trading controls</p>
<div id="cards" class="grid"></div><div class="grid"><section class="card"><h2>Shadow audit</h2><pre id="shadows">Loading…</pre></section>
<section class="card"><h2>Journal timeline</h2><pre id="journal">Loading…</pre></section></div>
<script>fetch('/dashboard/state').then(r=>r.json()).then(d=>{{
document.querySelector('#cards').innerHTML=[['Audit events',d.event_count],['Shadow trades',d.summary.shadow_trade_count],['Completed audits',d.summary.completed_shadow_audits],['Selected − shadow P&L','$'+d.summary.selected_minus_shadow_pnl]].map(x=>`<div class="card"><div class="sub">${{x[0]}}</div><div class="n">${{x[1]}}</div></div>`).join('');
document.querySelector('#shadows').textContent=JSON.stringify(d.shadows,null,2);document.querySelector('#journal').textContent=JSON.stringify(d.journal,null,2);}}).catch(e=>document.body.append('Dashboard error: '+e));</script>
</body></html>"""
