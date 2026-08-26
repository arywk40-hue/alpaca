"""Deterministic quote-implied option inputs used only when Alpaca omits Greeks."""

from __future__ import annotations

from math import erf, exp, log, sqrt


def normal_cdf(value: float) -> float:
    return (1.0 + erf(value / sqrt(2.0))) / 2.0


def black_scholes_price(
    *,
    spot: float,
    strike: float,
    years: float,
    volatility: float,
    option_type: str,
    rate: float = 0.04,
) -> float | None:
    if (
        spot <= 0
        or strike <= 0
        or years <= 0
        or volatility <= 0
        or option_type not in {"call", "put"}
    ):
        return None
    sigma_sqrt_t = volatility * sqrt(years)
    d1 = (log(spot / strike) + (rate + volatility**2 / 2) * years) / sigma_sqrt_t
    d2 = d1 - sigma_sqrt_t
    discounted_strike = strike * exp(-rate * years)
    if option_type == "call":
        return spot * normal_cdf(d1) - discounted_strike * normal_cdf(d2)
    return discounted_strike * normal_cdf(-d2) - spot * normal_cdf(-d1)


def quote_implied_volatility(
    *,
    spot: float,
    strike: float,
    years: float,
    option_price: float,
    option_type: str,
    rate: float = 0.04,
) -> float | None:
    """Invert Black–Scholes from an observed quote midpoint using bisection.

    This is a documented mathematical transform of live quote data, never a
    forecast. It is intentionally rejected when the observed price is outside
    no-arbitrage bounds or cannot be solved within a conservative range.
    """
    if (
        spot <= 0
        or strike <= 0
        or years <= 0
        or option_price <= 0
        or option_type not in {"call", "put"}
    ):
        return None
    discounted_strike = strike * exp(-rate * years)
    lower = (
        max(0.0, spot - discounted_strike)
        if option_type == "call"
        else max(0.0, discounted_strike - spot)
    )
    upper = spot if option_type == "call" else discounted_strike
    if not lower < option_price < upper:
        return None
    low, high = 0.001, 5.0
    high_price = black_scholes_price(
        spot=spot, strike=strike, years=years, volatility=high, option_type=option_type, rate=rate
    )
    if high_price is None or high_price < option_price:
        return None
    for _ in range(80):
        midpoint = (low + high) / 2
        price = black_scholes_price(
            spot=spot,
            strike=strike,
            years=years,
            volatility=midpoint,
            option_type=option_type,
            rate=rate,
        )
        assert price is not None
        if price < option_price:
            low = midpoint
        else:
            high = midpoint
    return round((low + high) / 2, 6)


def black_scholes_delta(
    *,
    spot: float,
    strike: float,
    years: float,
    volatility: float,
    option_type: str,
    rate: float = 0.04,
) -> float | None:
    if (
        spot <= 0
        or strike <= 0
        or years <= 0
        or volatility <= 0
        or option_type not in {"call", "put"}
    ):
        return None
    d1 = (log(spot / strike) + (rate + volatility**2 / 2) * years) / (volatility * sqrt(years))
    call_delta = normal_cdf(d1)
    return call_delta if option_type == "call" else call_delta - 1
