from datetime import date

from vegaguard.scanner import daily_return, parse_option_symbol, realized_volatility


def test_parses_occ_option_symbol():
    parsed = parse_option_symbol("SPY260918C00650000")
    assert parsed == ("SPY", date(2026, 9, 18), "call", 650.0)


def test_market_indicators_are_calculated():
    closes = [100, 101, 102, 104, 103, 106, 108]
    assert round(daily_return(closes, 1), 2) == 1.89
    assert daily_return(closes, 5) > 0
    assert realized_volatility(closes) > 0
