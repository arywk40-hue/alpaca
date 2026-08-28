# Strategy and risk rules

Universe: SPY, QQQ, and IWM. VegaGuard uses only one-contract bull-call or bear-put debit spreads with 14–28 days to expiry by default. It rejects naked options and incomplete or illiquid legs.

The signal score combines daily direction, intraday EMA/VWAP trend, volume confirmation, realized-versus-implied volatility state, and SPY market alignment. It is numeric from -100 to 100. A score with sufficient aligned evidence is `bullish` or `bearish`; complete but non-actionable evidence is `neutral`. `no_trade` means safe scoring was impossible, for example `missing_iv`, `stale_iv`, `insufficient_iv_history`, insufficient bars, or no completed session bar.

Quotes must be fresh, non-crossed, and inside the configured bid/ask-spread limit. When Alpaca supplies official IV and Greeks they are used. If it does not, VegaGuard may calculate a labelled quote-derived IV and delta only from a fresh observed bid/ask, OCC symbol metadata, spot, and the configured risk-free rate. It does not synthesize market data or forecast IV.

Entry is a positive debit limit. Maximum loss is the debit times 100 times contracts; maximum profit is spread width less debit, times 100 times contracts. The guardian uses conservative executable value (long bid less short ask), exits at +50% profit or -35% loss, and also exits on signal reversal, three-day time stop, or two days to expiry. All exits reverse both legs atomically.

Paper results are not evidence of future real-market performance.

## Fixed-horizon replay exits

Historical replay can additionally use `--exit-horizon-minutes 15`, `30`, or `60`
to close a spread on the first fresh quote event at or after that elapsed horizon.
It still enters with long-ask/short-bid and exits with long-bid/short-ask, applies
only declared fee/slippage assumptions, and rejects an unavailable exit quote. This
is offline research-only and has no effect on the guardian or paper execution.

Its results expose `expectancy_usd_per_trade` and `missing_data_rate` beside win rate,
profit factor, and drawdown. The missing-data denominator is valid feature observations plus
rejections caused by incomplete signal or option evidence; neutral signals are not treated as
missing data.

## Research-only conflict experiment

The production scanner uses the baseline scorer. `score_signal_conflict_tolerant` is an offline experiment only; it is never imported by the scanner, scheduler, or execution path. When daily and intraday trends conflict, it uses the completed daily trend provisionally, applies a five-point penalty, retains the 70-point threshold, and requires daily direction plus volume, volatility, and market alignment before it can classify a trade.

Run the A/B report only on point-in-time replay data:

```bash
vegaguard strategy compare-scorers \
  --fixture tests/fixtures/strategy_replay_sanitized.json
```

The report includes trade count, net P&L after costs, win rate, profit factor, maximum drawdown, rejection reasons, and regime distribution. It explicitly marks missing normalized historical option data as no out-of-sample assessment. Do not promote the experimental scorer to live use without a separate, statistically meaningful point-in-time historical result and an execution-risk review.

## Historical walk-forward threshold study

`vegaguard strategy walk-forward` evaluates thresholds 40, 50, 60, and 70 only from local
normalized point-in-time data. It uses the earlier chronological window to choose at most one
research threshold, then reports its later held-out result. The production scanner still calls the
baseline scorer at 70; this command has no configuration or execution side effects. No selection is
made unless the in-sample input is labelled `REAL HISTORICAL OPTION BACKTEST` and has the configured
minimum trade count. A selected research threshold is never automatically promoted.

## Offline confidence calibration

`vegaguard strategy calibrate-confidence` replays a local cache at an explicit research-only
minimum score, then groups completed option trades by absolute entry score and direction. It reports
observed win rate, a small-sample-smoothed empirical rate, conservative net P&L and profit factor.
It labels its output `insufficient_real_historical_evidence` unless the completed backtest is genuine
and each displayed bucket reaches the requested sample minimum. The live score remains a deterministic
strength score—not a probability—and this command does not affect the fixed production threshold of 70.

## Option-surface research features

Live scans persist a median IV observation for each underlying and retain an append-only local IV
history. The shadow ledger records research-only option-surface values when the observed chain can
support them: IV percentile after at least 20 observations, near-the-money put-minus-call IV skew,
and 14–21 versus 22–28 DTE term structure. Missing history or missing contract buckets remain
`null`; stock volatility is never substituted. These features currently explain and evaluate
candidates only—they do not lower the production 70-point threshold or bypass any risk gate.

IV history and raw option quotes are always read as-of the scanner timestamp. A future-dated
observation or quote is excluded rather than treated as fresh, preventing point-in-time leakage.

The same offline report also compares the unchanged baseline scorer at thresholds 40, 50, 60, and 70.
These metrics are exploratory only; they do not update the live production threshold.

## Shadow-candidate ledger

The production baseline scorer records every market-hours decision in the local shadow-candidate ledger, including directionless/no-data decisions, below-threshold directional candidates, rejected spreads, and qualifying candidates. Each record has its observed/data timestamps, explicit reasons, and—when a hypothetical defined-risk spread exists—the two real option-quote timestamps and conservative spread economics. This is evidence gathering only: it does not lower the 70-point threshold and cannot submit an order.

```bash
# Run a bounded shadow cycle. DRY_RUN means no MCP order call.
ALLOW_ORDER_EXECUTION=true DRY_RUN=true \
  vegaguard live run-scheduler --interval-seconds 900 --max-cycles 1

# Inspect the durable records or dashboard state.
vegaguard live shadow-candidates --limit 20
```

## Paper-only exploration mode

`EXPLORATION_MODE=false` is the default. When explicitly enabled with
`EXPLORATION_SCORE_THRESHOLD=40`, it retains the baseline scorer but admits a directional 40-point score
only after all production quote freshness, IV, liquidity, DTE, debit-spread, buying-power, position, and
maximum-loss gates pass. Exploration can open one whole-contract defined-risk debit spread only and will
not run while any position is open. Its plans and ledger records are labelled `exploration`; production
plans stay labelled `production` and retain the 70-point threshold.

Candidate records distinguish an executable conservative entry quote from a filled entry. Their
entry/exit quote, costs, and P&L fields stay `null`; later fill and executable-exit-mark events add only
the observed facts. No fee, fill, or P&L value is inferred.
