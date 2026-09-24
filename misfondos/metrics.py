"""Cálculos de rentabilidad sobre el histórico de valores liquidativos.

Todas las rentabilidades de un periodo se miden igual en toda la app (indicador
de la cabecera y tabla de rentabilidades): VL actual frente al VL de la fecha de
inicio del periodo o, si ese día no hubo VL, el último anterior. "En lo que va
de año" usa el último VL del año anterior, que es el criterio habitual.
"""
import pandas as pd

from . import portfolio

_OFFSETS = {
    "1M": pd.DateOffset(months=1),
    "3M": pd.DateOffset(months=3),
    "6M": pd.DateOffset(months=6),
    "1A": pd.DateOffset(years=1),
    "3A": pd.DateOffset(years=3),
    "5A": pd.DateOffset(years=5),
}
_YEARS = {"3A": 3, "5A": 5}
# Si el histórico empieza más de una semana después del inicio del periodo, no
# hay datos suficientes para medirlo (p.ej. un fondo lanzado hace 2 años no
# tiene rentabilidad a 3 años).
_TOLERANCE = pd.Timedelta(days=7)


def period_start(closes, key):
    last = closes.index[-1]
    if key == "YTD":
        return pd.Timestamp(year=last.year - 1, month=12, day=31)
    if key == "Todo":
        return closes.index[0]
    return last - _OFFSETS[key]


def period_return(closes, key, annualize=False):
    """Rentabilidad en % del periodo (1M, 3M, 6M, YTD, 1A, 3A, 5A, Todo), o None
    si el histórico no cubre el periodo. `annualize` convierte 3A/5A en media anual."""
    closes = closes.dropna() if closes is not None else closes
    if closes is None or len(closes) < 2:
        return None
    last = float(closes.iloc[-1])
    if key == "Todo":
        base = float(closes.iloc[0])
    else:
        start = period_start(closes, key)
        if closes.index[0] > start + _TOLERANCE:
            return None
        base = portfolio.nav_on(closes, start.date())
    if not base:
        return None
    ratio = last / base
    if annualize and key in _YEARS:
        ratio = ratio ** (1 / _YEARS[key])
    return (ratio - 1) * 100
