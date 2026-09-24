import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request

import pandas as pd

from . import store

_HEADERS = {"User-Agent": "Mozilla/5.0"}
_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range={}&interval=1d"


def _download(ticker, range_, retries=3):
    url = _CHART_URL.format(ticker, range_)
    last_exc = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    else:
        raise last_exc

    result = data.get("chart", {}).get("result")
    if not result:
        return pd.DataFrame(columns=["Close"])

    result = result[0]
    timestamps = result.get("timestamp") or []
    if not timestamps:
        return pd.DataFrame(columns=["Close"])

    quote = result["indicators"]["quote"][0]
    adjclose_list = result["indicators"].get("adjclose")
    closes = adjclose_list[0]["adjclose"] if adjclose_list else quote.get("close")

    dates = [dt.datetime.utcfromtimestamp(t) for t in timestamps]
    df = pd.DataFrame({"Close": closes}, index=pd.DatetimeIndex(dates, name="Date"))
    df = df.dropna()
    df.attrs["currency"] = (result.get("meta") or {}).get("currency") or ""
    return df


def fetch_initial_history(ticker):
    """Descarga el histórico inicial de un fondo (usado al agregarlo)."""
    df = _download(ticker, range_="10y")
    if df.empty:
        df = _download(ticker, range_="max")
    return df


def load_history(fund_id):
    path = store.history_path(fund_id)
    if not os.path.exists(path):
        return pd.DataFrame(columns=["Close"])
    df = pd.read_csv(path, index_col="Date", parse_dates=True)
    return df


def save_history(fund_id, df):
    path = store.history_path(fund_id)
    df.sort_index().to_csv(path)


def refresh_fund(fund, initial=False):
    """Descarga datos nuevos para un fondo y los fusiona con el histórico local."""
    ticker = fund["ticker"]
    if initial:
        new_df = fetch_initial_history(ticker)
    else:
        new_df = _download(ticker, range_="1mo")

    # Los fondos añadidos antes de guardar la divisa la tienen vacía; se completa aquí.
    currency = new_df.attrs.get("currency")
    if currency and not fund.get("currency"):
        store.update_fund(fund["id"], currency=currency)

    existing_df = load_history(fund["id"])
    combined = pd.concat([existing_df, new_df])
    combined = combined[~combined.index.duplicated(keep="last")]
    combined = combined.sort_index()
    save_history(fund["id"], combined)
    return combined


def refresh_all(funds, on_progress=None):
    for fund in funds:
        try:
            refresh_fund(fund, initial=False)
        except Exception as exc:  # noqa: BLE001 - se informa en la UI, no debe tirar el hilo
            if on_progress:
                on_progress(fund, error=exc)
                continue
        if on_progress:
            on_progress(fund, error=None)
