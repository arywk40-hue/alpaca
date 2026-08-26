import pytest

from vegaguard.strategy.options_math import (
    black_scholes_delta,
    black_scholes_price,
    quote_implied_volatility,
)


def test_quote_implied_volatility_recovers_the_observed_black_scholes_value():
    price = black_scholes_price(
        spot=100, strike=100, years=21 / 365, volatility=0.2, option_type="call"
    )
    assert price is not None
    implied = quote_implied_volatility(
        spot=100, strike=100, years=21 / 365, option_price=price, option_type="call"
    )
    assert implied == pytest.approx(0.2, abs=0.0001)
    delta = black_scholes_delta(
        spot=100, strike=100, years=21 / 365, volatility=implied, option_type="call"
    )
    assert delta == pytest.approx(0.53, abs=0.02)


def test_quote_implied_volatility_rejects_an_impossible_option_price():
    assert (
        quote_implied_volatility(
            spot=100, strike=100, years=21 / 365, option_price=101, option_type="call"
        )
        is None
    )
