# Strategy and risk rules

Universe: SPY, QQQ, and IWM. VegaGuard uses only one-contract bull-call or bear-put debit spreads with 14–28 days to expiry by default. It rejects naked options and incomplete or illiquid legs.

The signal score combines daily direction, intraday EMA/VWAP trend, volume confirmation, realized-versus-implied volatility state, and SPY market alignment. It is numeric from -100 to 100. A score with sufficient aligned evidence is `bullish` or `bearish`; complete but non-actionable evidence is `neutral`. `no_trade` means safe scoring was impossible, for example `missing_iv`, `stale_iv`, `insufficient_iv_history`, insufficient bars, or no completed session bar.

Quotes must be fresh, non-crossed, and inside the configured bid/ask-spread limit. When Alpaca supplies official IV and Greeks they are used. If it does not, VegaGuard may calculate a labelled quote-derived IV and delta only from a fresh observed bid/ask, OCC symbol metadata, spot, and the configured risk-free rate. It does not synthesize market data or forecast IV.

Entry is a positive debit limit. Maximum loss is the debit times 100 times contracts; maximum profit is spread width less debit, times 100 times contracts. The guardian uses conservative executable value (long bid less short ask), exits at +50% profit or -35% loss, and also exits on signal reversal, three-day time stop, or two days to expiry. All exits reverse both legs atomically.

Paper results are not evidence of future real-market performance.
