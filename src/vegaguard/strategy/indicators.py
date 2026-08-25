from collections.abc import Sequence
from math import sqrt


def ema(values: Sequence[float], period: int) -> list[float]:
    """Exponential moving average, seeded from the first observation."""
    if period < 1:
        raise ValueError("period must be positive")
    if not values:
        return []
    multiplier = 2 / (period + 1)
    output = [float(values[0])]
    for value in values[1:]:
        output.append((float(value) - output[-1]) * multiplier + output[-1])
    return output


def percent_return(values: Sequence[float], periods: int) -> float:
    if periods < 1:
        raise ValueError("periods must be positive")
    if len(values) <= periods or values[-1 - periods] == 0:
        return 0.0
    return (float(values[-1]) / float(values[-1 - periods]) - 1) * 100


def realized_volatility(closes: Sequence[float], annualization: int = 252) -> float:
    if len(closes) < 3:
        return 0.0
    returns = [float(closes[i]) / float(closes[i - 1]) - 1 for i in range(1, len(closes))]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return sqrt(variance) * sqrt(annualization)


def vwap(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], volumes: Sequence[float]
) -> float:
    if not (len(highs) == len(lows) == len(closes) == len(volumes)):
        raise ValueError("OHLCV sequences must have equal length")
    total_volume = sum(float(volume) for volume in volumes)
    if total_volume <= 0:
        return 0.0
    total_price_volume = sum(
        ((float(high) + float(low) + float(close)) / 3) * float(volume)
        for high, low, close, volume in zip(highs, lows, closes, volumes, strict=True)
    )
    return total_price_volume / total_volume


def volume_ratio(volumes: Sequence[float], baseline_period: int = 20) -> float:
    if baseline_period < 1:
        raise ValueError("baseline_period must be positive")
    if len(volumes) < 2:
        return 0.0
    baseline = list(volumes[-baseline_period - 1 : -1])
    if not baseline:
        return 0.0
    average = sum(float(value) for value in baseline) / len(baseline)
    return float(volumes[-1]) / average if average > 0 else 0.0
