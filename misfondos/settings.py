import json
import os

from . import config


def _load():
    if not os.path.exists(config.SETTINGS_FILE):
        return {}
    try:
        with open(config.SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data):
    with open(config.SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_theme():
    data = _load()
    theme = data.get("theme", config.DEFAULT_THEME)
    if theme not in config.THEMES:
        theme = config.DEFAULT_THEME
    return theme


def set_theme(theme_name):
    if theme_name not in config.THEMES:
        raise ValueError(f"Tema desconocido: {theme_name}")
    data = _load()
    data["theme"] = theme_name
    _save(data)


# ---------- ajustes del programa (comunes a todos los usuarios) ----------
# El tema es de cada usuario (config.SETTINGS_FILE apunta a su carpeta); lo que va
# aquí afecta al programa en sí, que es uno solo para todos.
APP_SETTINGS_FILE = os.path.join(config.DATA_DIR, "app_settings.json")


def _load_app():
    try:
        with open(APP_SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_app(data):
    with open(APP_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_close_to_tray():
    """Si cerrar con la X deja el programa funcionando junto al reloj (por defecto sí)."""
    return bool(_load_app().get("close_to_tray", True))


def set_close_to_tray(enabled):
    data = _load_app()
    data["close_to_tray"] = bool(enabled)
    _save_app(data)


def tray_notice_shown():
    return bool(_load_app().get("tray_notice_shown", False))


def mark_tray_notice_shown():
    data = _load_app()
    data["tray_notice_shown"] = True
    _save_app(data)
