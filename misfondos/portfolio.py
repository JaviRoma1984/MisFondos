"""Aportaciones y reembolsos del usuario en cada fondo, y cálculo de su posición.

Las participaciones de un movimiento se guardan solo si el usuario las escribe
(p.ej. copiadas de MyInvestor). Si no, se calculan en cada consulta como
importe / valor liquidativo de esa fecha: así, una aportación apuntada hoy
antes de que se publique el VL de hoy usa el último disponible y se corrige
sola cuando llega el VL real.
"""
import datetime as dt
import json
import os
import threading
import uuid

import pandas as pd

from . import config

APORTACION = "aportacion"
REEMBOLSO = "reembolso"

_lock = threading.Lock()


def _load_raw():
    if not os.path.exists(config.PORTFOLIO_FILE):
        return {}
    with open(config.PORTFOLIO_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_raw(data):
    tmp = config.PORTFOLIO_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, config.PORTFOLIO_FILE)  # escritura atómica: nunca queda a medias


def movements(fund_id):
    with _lock:
        movs = _load_raw().get(fund_id, [])
    return sorted(movs, key=lambda m: m["date"])


def add_movement(fund_id, date, kind, amount, units=None):
    if kind not in (APORTACION, REEMBOLSO):
        raise ValueError(f"Tipo de movimiento desconocido: {kind}")
    if amount <= 0:
        raise ValueError("El importe tiene que ser mayor que cero")
    if units is not None and units <= 0:
        raise ValueError("Las participaciones tienen que ser mayores que cero")
    mov = {
        "id": uuid.uuid4().hex[:10],
        "date": date.isoformat(),
        "kind": kind,
        "amount": round(float(amount), 2),
        "units": None if units is None else float(units),
    }
    with _lock:
        data = _load_raw()
        data.setdefault(fund_id, []).append(mov)
        _save_raw(data)
    return mov


def remove_movement(fund_id, movement_id):
    with _lock:
        data = _load_raw()
        data[fund_id] = [m for m in data.get(fund_id, []) if m["id"] != movement_id]
        if not data[fund_id]:
            del data[fund_id]
        _save_raw(data)


def remove_fund(fund_id):
    with _lock:
        data = _load_raw()
        if data.pop(fund_id, None) is not None:
            _save_raw(data)


def nav_on(closes, date):
    """VL del día indicado o, si ese día no hubo (fin de semana, festivo, aún no
    publicado), el último anterior. None si la fecha es anterior al histórico."""
    if closes is None or closes.empty:
        return None
    day_end = pd.Timestamp(date) + pd.Timedelta(days=1)
    upto = closes[closes.index < day_end]
    if upto.empty:
        return None
    return float(upto.iloc[-1])


def movement_units(mov, closes):
    """(participaciones, origen): origen es 'manual', 'calculado' o None si no se
    pueden calcular (fecha anterior al histórico descargado)."""
    if mov.get("units"):
        return float(mov["units"]), "manual"
    nav = nav_on(closes, dt.date.fromisoformat(mov["date"]))
    if not nav:
        return None, None
    return mov["amount"] / nav, "calculado"


def position(fund_id, closes):
    """Resumen de la posición en un fondo, o None si no hay movimientos."""
    movs = movements(fund_id)
    if not movs:
        return None
    units = contributed = withdrawn = 0.0
    missing = 0
    for m in movs:
        u, _src = movement_units(m, closes)
        if u is None:
            missing += 1
            continue
        if m["kind"] == APORTACION:
            units += u
            contributed += m["amount"]
        else:
            units -= u
            withdrawn += m["amount"]
    last_nav = float(closes.iloc[-1]) if closes is not None and not closes.empty else None
    value = units * last_nav if last_nav is not None else None
    invested = contributed - withdrawn
    gain = value - invested if value is not None else None
    gain_pct = gain / invested * 100 if gain is not None and invested > 0 else None
    return {
        "movements": len(movs),
        "missing_nav": missing,
        "units": units,
        "contributed": contributed,
        "withdrawn": withdrawn,
        "invested": invested,
        "last_nav": last_nav,
        "last_date": closes.index[-1] if last_nav is not None else None,
        "value": value,
        "gain": gain,
        "gain_pct": gain_pct,
    }
