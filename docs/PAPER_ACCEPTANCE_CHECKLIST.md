# VegaGuard Paper Acceptance Checklist

This is the external verification gate for the dedicated Alpaca **paper** account. It is not a
request to use live credentials, move money, or submit a real-money order.

## 1. Credentials and tool boundary

Copy `.env.example` to `.env`, add only new paper-account credentials, and leave these settings:

```dotenv
ALPACA_PAPER_TRADE=true
ALLOW_ORDER_EXECUTION=false
DRY_RUN=true
```

Run:

```bash
vegaguard preflight
```

Expected result:

- `status` is `ready`;
- the report contains account/clock/option-snapshot results;
- required MCP tools are present, including `place_option_order`;
- `data/mcp_preflight.json` contains tool schemas but no credentials.

If the report is incomplete, correct `ALPACA_TOOLSETS` or the installed MCP server before
continuing. Do not loosen the MCP allowed-tool list in the app.

## 2. Read-only market-data proof

Run the scanner twice during a market session, at least one fresh observation apart:

```bash
vegaguard live read-only-cycle
```

The first pass may correctly abstain because IV state needs a second snapshot. On a later pass,
each underlying must show either a typed opportunity/spread or an explicit no-trade reason.

## 3. Order-shape proof without an order

Set `ALLOW_ORDER_EXECUTION=true` while keeping `DRY_RUN=true`, then run one bounded scheduler
cycle:

```bash
vegaguard live run-scheduler --interval-seconds 900 --max-cycles 1
```

If every deterministic and thesis gate passes, inspect `data/journal.jsonl` and confirm that the
recorded payload is an `mleg` limit order with one `buy_to_open` and one `sell_to_open` leg. The
MCP process must not have received an order in this mode.

## 4. Dedicated paper-order acceptance

Only after reviewing the dry-run payload, set `DRY_RUN=false`. Run a single bounded cycle; the
application can submit only a paper, defined-risk debit spread and has a unique client order ID.
Record the MCP receipt and the Alpaca paper order ID in the journal.

Use the monitor in a separate terminal:

```bash
vegaguard live monitor-trade-updates
```

After fill, the scheduler evaluates the conservative executable close value. On a deterministic
profit, stop, time, or expiry trigger it can submit only the reverse atomic multi-leg close. Confirm
the fill event updates the selected-versus-no-trade shadow record in the dashboard.

## 5. Demo evidence

With the API running, open `http://127.0.0.1:8000/`. Capture the following in the demo:

1. preflight report and paper-only settings;
2. scanner score, committee reviews, and risk decision;
3. dry-run or paper MCP receipt and trade-update lifecycle;
4. journal timeline plus immutable shadow-audit outcome.

Do not claim paper performance, execution quality, or external Alpaca/OpenAI integration until this
checklist has been completed with recorded paper-account output.
