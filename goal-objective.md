# VegaGuard final objective

Demonstrate a bounded, paper-only options lifecycle:

`live observation → deterministic candidate → defined-risk debit spread → risk approval → exact-plan Alpaca MCP paper submission → acknowledgement/fill monitoring → deterministic exit → realized paper P&L → audit dashboard`

Production scoring remains fixed at 70. Execution defaults to disabled and dry-run. Simulation, hypothetical shadow outcomes, approved plans, submitted paper orders, paper fills, and realized paper P&L are separate evidence classes. No implementation or test command may submit an order or call the MCP execution tool.

The completion boundary is documented in `reports/final_readiness_report.md`. A genuine paper lifecycle remains external acceptance evidence until Alpaca acknowledges and fills an explicitly reviewed plan during an open options session.
