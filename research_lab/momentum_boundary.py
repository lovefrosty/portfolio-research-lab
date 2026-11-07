"""Versioned numeric boundary for diagnostic momentum, not an admitted signal."""
from decimal import Decimal, InvalidOperation, localcontext
import math

RULE_ID = 'momentum_endpoint_deadband_v1'
EPSILON = Decimal('1e-12')  # cumulative simple price change over the whole lookback


def boundary_sign(start, end) -> float:
    """Inclusive symmetric deadband, evaluated from decimal input representations."""
    try:
        a, b = Decimal(str(start)), Decimal(str(end))
    except InvalidOperation as exc:
        raise ValueError('invalid_boundary_price') from exc
    if not a.is_finite() or not b.is_finite() or a <= 0 or b <= 0:
        raise ValueError('invalid_boundary_price')
    with localcontext() as ctx:
        # Enough precision for exact subtraction/multiplication for these decimals.
        ctx.prec = max(50, len(a.as_tuple().digits) + len(b.as_tuple().digits)
                       + abs(a.adjusted()-b.adjusted()) + 20)
        delta = b-a
        if abs(delta) <= EPSILON*a:
            return 0.0
        return 1.0 if delta > 0 else -1.0


def positions(prices, window: int = 5) -> list[float]:
    """Position at t uses endpoints t-window-1 and t-1; warmup stays NaN."""
    if type(window) is not int or window < 1:
        raise ValueError('invalid_boundary_window')
    for price in prices:
        boundary_sign(price, price)
    result = [math.nan] * len(prices)
    for t in range(window+1, len(prices)):
        result[t] = boundary_sign(prices[t-window-1], prices[t-1])
    return result
