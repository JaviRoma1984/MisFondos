import json
import os
import threading

from . import config

_lock = threading.Lock()


def _load_raw():
    if not os.path.exists(config.FUNDS_FILE):
        return []
    with open(config.FUNDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_raw(funds):
    with open(config.FUNDS_FILE, "w", encoding="utf-8") as f:
        json.dump(funds, f, ensure_ascii=False, indent=2)


def list_funds():
    with _lock:
        return _load_raw()


def next_color(existing_funds):
    used = {f["color"] for f in existing_funds}
    for color in config.COLOR_PALETTE:
        if color not in used:
            return color
    # Si se agotó la paleta, se repite cíclicamente
    return config.COLOR_PALETTE[len(existing_funds) % len(config.COLOR_PALETTE)]


def add_fund(name, isin, ticker, currency):
    with _lock:
        funds = _load_raw()
        if any(f["isin"] == isin for f in funds):
            raise ValueError(f"El ISIN {isin} ya está en la lista")
        fund = {
            "id": isin,
            "name": name,
            "isin": isin,
            "ticker": ticker,
            "currency": currency,
            "color": next_color(funds),
        }
        funds.append(fund)
        _save_raw(funds)
        return fund


def update_fund(fund_id, **fields):
    with _lock:
        funds = _load_raw()
        for f in funds:
            if f["id"] == fund_id:
                f.update(fields)
        _save_raw(funds)


def remove_fund(fund_id):
    with _lock:
        funds = _load_raw()
        funds = [f for f in funds if f["id"] != fund_id]
        _save_raw(funds)


def history_path(fund_id):
    safe_id = fund_id.replace("/", "_").replace("\\", "_")
    return os.path.join(config.HISTORY_DIR, f"{safe_id}.csv")
