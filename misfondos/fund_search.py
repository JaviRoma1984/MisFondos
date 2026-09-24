import json
import time
import urllib.error
import urllib.parse
import urllib.request

from . import applog

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}
_YAHOO_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
_FT_SEARCH_URL = "https://markets.ft.com/data/searchapi/searchsecurities?query={}"


def _get_json(url, timeout=10):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _yahoo_quotes(query):
    """Busca en Yahoo probando los dos hosts y reintentando si limita peticiones (429).
    Devuelve [] si alguna consulta respondió bien pero sin resultados; solo lanza la
    excepción si TODOS los intentos fallaron (sin red, bloqueo, etc.)."""
    last_exc = None
    answered = False
    for attempt, host in enumerate(_YAHOO_HOSTS * 2):
        url = f"https://{host}/v1/finance/search?q={urllib.parse.quote(query)}&quotesCount=10&newsCount=0"
        try:
            quotes = _get_json(url).get("quotes", [])
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code == 429:
                time.sleep(1.5 * (attempt + 1))
            continue
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last_exc = exc
            continue
        answered = True
        if quotes:
            return quotes
    if not answered and last_exc is not None:
        raise last_exc
    return []


def official_name(isin):
    """Nombre oficial del fondo según Financial Times. Yahoo a menudo solo tiene un
    código interno (p.ej. '0P0001CC4K.F') como nombre, que el usuario no reconoce."""
    try:
        data = _get_json(_FT_SEARCH_URL.format(urllib.parse.quote(isin)), timeout=8)
    except Exception:  # noqa: BLE001 - el nombre es un extra, la búsqueda sigue sin él
        applog.warning("No se pudo consultar el nombre en FT para %s", isin)
        return None
    for sec in data.get("data", {}).get("security", []):
        if sec.get("symbol", "").upper().split(":")[0] == isin.upper():
            return (sec.get("name") or "").strip() or None
    return None


def _is_cryptic(name, symbol):
    return not name or name.strip().upper() == symbol.upper()


def search_by_isin(isin):
    """Devuelve candidatos {symbol, name, exchange} para un ISIN, con el nombre real
    del fondo cuando Yahoo solo da su código interno."""
    fund_name = official_name(isin)
    quotes = _yahoo_quotes(isin)

    # Si Yahoo no encuentra el ISIN, a veces sí encuentra el fondo por su nombre.
    if not quotes and fund_name:
        applog.info("Yahoo sin resultados para %s; reintentando por nombre '%s'", isin, fund_name)
        quotes = _yahoo_quotes(fund_name)

    candidates = []
    for q in quotes:
        symbol = q.get("symbol")
        if not symbol:
            continue
        yahoo_name = q.get("longname") or q.get("shortname") or ""
        name = fund_name or (yahoo_name if not _is_cryptic(yahoo_name, symbol) else symbol)
        candidates.append({"symbol": symbol, "name": name.strip(), "exchange": q.get("exchange", "")})

    applog.info(
        "Búsqueda %s: nombre FT=%r, %d resultado(s) en Yahoo: %s",
        isin, fund_name, len(candidates), [c["symbol"] for c in candidates],
    )
    return candidates
