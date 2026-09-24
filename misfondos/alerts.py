"""Alertas de caída: aviso de Windows cuando un fondo baja un X % o más en un día
(último VL frente al anterior) o en una semana (frente al VL de 7 días antes).

Cada aviso salta una sola vez: el de un día, una vez por cada VL nuevo; el de una
semana, como mucho una vez cada 7 días por fondo (si no, una caída sostenida
volvería a avisar cada día de la semana siguiente). Lo ya avisado y un historial
corto de los últimos avisos se guardan por usuario en config.ALERTS_FILE.
"""
import datetime as dt
import json
import os

import pandas as pd

from . import config

DAY, WEEK = "day", "week"
KIND_TEXT = {DAY: "en un día", WEEK: "en una semana"}
# Umbrales que se pueden elegir (en %) y los de fábrica.
OPTIONS = {DAY: [1, 2, 3, 5], WEEK: [3, 5, 8, 10]}
DEFAULTS = {DAY: {"on": True, "pct": 2}, WEEK: {"on": True, "pct": 5}}
# Un VL más viejo que esto ya no avisa: el fondo ha dejado de actualizarse y la
# caída es historia, no noticia.
STALE_DAYS = 5
HISTORY_MAX = 30


def _load():
    try:
        with open(config.ALERTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save(data):
    tmp = config.ALERTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, config.ALERTS_FILE)


def change(closes, kind):
    """Variación del último VL en un día o en una semana, o None si no se puede
    calcular (poco histórico, o un hueco de datos justo donde hace falta)."""
    closes = closes.dropna()
    if len(closes) < 2:
        return None
    last_date, last = closes.index[-1], float(closes.iloc[-1])
    if kind == DAY:
        base_date, base = closes.index[-2], float(closes.iloc[-2])
    else:
        target = last_date - pd.Timedelta(days=7)
        earlier = closes[closes.index <= target]
        if earlier.empty:
            return None
        base_date, base = earlier.index[-1], float(earlier.iloc[-1])
        if (target - base_date).days > 4:  # hueco en el histórico: la comparación no sería de una semana
            return None
    if base <= 0:
        return None
    return {"pct": (last / base - 1) * 100, "from_nav": base, "from_date": base_date.date(),
            "to_nav": last, "to_date": last_date.date()}


def check(funds, closes_of, rules, today=None):
    """Avisos nuevos para estos fondos según las reglas del usuario (y los deja
    apuntados como avisados, para no repetirlos). `closes_of(fund_id)` devuelve la
    serie de VL del fondo."""
    today = today or dt.date.today()
    data = _load()
    notified = data.setdefault("notified", {})
    new = []
    for fund in funds:
        closes = None
        for kind in (DAY, WEEK):
            rule = rules[kind]
            if not rule["on"]:
                continue
            if closes is None:
                closes = closes_of(fund["id"])
            ch = change(closes, kind)
            if ch is None or ch["pct"] > -rule["pct"]:
                continue
            if (today - ch["to_date"]).days > STALE_DAYS:
                continue
            key = f"{fund['id']}|{kind}"
            prev = notified.get(key)
            if prev:
                prev = dt.date.fromisoformat(prev)
                if kind == DAY and ch["to_date"] <= prev:
                    continue
                if kind == WEEK and (ch["to_date"] - prev).days < 7:
                    continue
            notified[key] = ch["to_date"].isoformat()
            new.append({
                "fund_id": fund["id"], "name": fund["name"], "kind": kind, "threshold": rule["pct"],
                "pct": round(ch["pct"], 4), "from_nav": ch["from_nav"], "from_date": ch["from_date"].isoformat(),
                "to_nav": ch["to_nav"], "to_date": ch["to_date"].isoformat(),
                "at": dt.datetime.now().isoformat(timespec="seconds"),
            })
    if new:
        data["history"] = (new + data.get("history", []))[:HISTORY_MAX]
        _save(data)
    return new


def history():
    """Últimos avisos del usuario activo, del más reciente al más antiguo."""
    return _load().get("history", [])
