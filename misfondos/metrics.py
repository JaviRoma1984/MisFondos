"""Cálculos de rentabilidad y de riesgo sobre el histórico de valores liquidativos.

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


# ---------- riesgo ----------
# Tramos de volatilidad anual (%) de la escala oficial de riesgo de los folletos
# (SRRI, del 1 al 7). La oficial se calcula con 5 años de datos semanales; aquí se
# aplica a la volatilidad del periodo elegido, así que es orientativa.
SRRI_LIMITS = [0.5, 2, 5, 10, 15, 25]
# Con menos variaciones que estas no se calcula nada (el resultado no significaría nada).
_MIN_RETURNS = 10


def period_window(closes, key):
    """VL del periodo: desde el del día de inicio (o el último anterior, el mismo
    que usa period_return) hasta el último. None si el histórico no lo cubre."""
    closes = closes.dropna() if closes is not None else closes
    if closes is None or len(closes) < 2:
        return None
    if key == "Todo":
        return closes
    start = period_start(closes, key)
    if closes.index[0] > start + _TOLERANCE:
        return None
    upto = closes[closes.index < start.normalize() + pd.Timedelta(days=1)]
    first = upto.index[-1] if len(upto) else closes.index[0]
    return closes[closes.index >= first]


def risk_level(volatility):
    """Nivel de riesgo del 1 al 7 según la volatilidad anual en %."""
    return 1 + sum(volatility >= limit for limit in SRRI_LIMITS)


def risk(closes, key):
    """Métricas de riesgo del periodo, o None si no hay datos suficientes:
    - volatility: desviación típica anualizada de las variaciones diarias (%)
    - level: nivel de riesgo aproximado 1-7 (tramos SRRI)
    - max_drawdown: peor caída desde un máximo hasta el mínimo posterior (%, ≤ 0),
      con peak_date / trough_date, y recovery_days: días desde ese máximo hasta
      volver a él (None si aún no ha vuelto)
    - from_max: cuánto está el último VL por debajo del máximo del periodo (%, ≤ 0)
    - worst_day: peor variación de un día (%) y su fecha
    """
    s = period_window(closes, key)
    if s is None:
        return None
    rets = s.pct_change().dropna()
    if len(rets) < _MIN_RETURNS:
        return None
    # Observaciones por año según los propios datos: casi todos los fondos dan un VL
    # por día laborable (~252), pero algunos lo publican semanal y con 252 fijo su
    # volatilidad saldría muy por debajo de la real.
    years = (s.index[-1] - s.index[0]).days / 365.25
    per_year = len(rets) / years if years > 0 else 252
    volatility = float(rets.std(ddof=1) * per_year ** 0.5 * 100)

    drawdown = s / s.cummax() - 1
    trough_date = drawdown.idxmin()
    max_dd = float(drawdown.min() * 100)
    peak_date = recovery_days = None
    if max_dd < 0:
        peak_date = s.loc[:trough_date].idxmax()
        after = s.loc[trough_date:]
        back = after[after >= s.loc[peak_date]]
        if len(back):
            recovery_days = int((back.index[0] - peak_date).days)
    return {
        "volatility": volatility,
        "level": risk_level(volatility),
        "max_drawdown": max_dd,
        "peak_date": peak_date,
        "trough_date": trough_date if max_dd < 0 else None,
        "recovery_days": recovery_days,
        "from_max": float((s.iloc[-1] / s.max() - 1) * 100),
        "worst_day": float(rets.min() * 100),
        "worst_day_date": rets.idxmin(),
        "start": s.index[0],
        "end": s.index[-1],
    }
