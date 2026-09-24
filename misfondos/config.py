import os
import sys

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
    # Los recursos empaquetados con --add-data se extraen a una carpeta temporal,
    # no junto al .exe (ahí solo vive data/, que es del usuario).
    RESOURCE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    RESOURCE_DIR = APP_DIR

ICON_FILE = os.path.join(RESOURCE_DIR, "assets", "misfondos.ico")
LOGO_FILE = os.path.join(RESOURCE_DIR, "assets", "misfondos.png")

DATA_DIR = os.path.join(APP_DIR, "data")
FUNDS_FILE = os.path.join(DATA_DIR, "funds.json")
HISTORY_DIR = os.path.join(DATA_DIR, "history")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.json")
ALERTS_FILE = os.path.join(DATA_DIR, "alerts.json")  # users.py lo apunta a la carpeta del usuario

# Los fondos publican un valor liquidativo al día, a una hora que varía según la
# gestora; comprobar cada 15 min hace que el dato nuevo aparezca poco después de
# publicarse sin que el usuario haga nada (son unas pocas peticiones pequeñas).
REFRESH_INTERVAL_SECONDS = 15 * 60

DEFAULT_THEME = "oscuro"

# Cada tema define los mismos "roles" de color, usados en toda la interfaz.
THEMES = {
    "oscuro": {
        "label": "Modo oscuro",
        "appearance": "dark",
        "bg_app": "#12121c",
        "bg_sidebar": "#181826",
        "bg_card": "#1f1f30",
        "bg_card_hover": "#272740",
        "bg_card_selected": "#3d2e66",
        "border": "#3a3a52",
        "text_primary": "#eef0f8",
        "text_muted": "#8c8ca6",
        "accent": "#8b5cf6",
        "accent_hover": "#7c3aed",
        "grid": "#33334a",
        "swatch": ["#12121c", "#8b5cf6"],
    },
    "rojo": {
        "label": "Rojo y negro",
        "appearance": "dark",
        "bg_app": "#0a0a0a",
        "bg_sidebar": "#111111",
        "bg_card": "#171717",
        "bg_card_hover": "#241a1a",
        "bg_card_selected": "#5a1519",
        "border": "#4d3131",
        "text_primary": "#f5eeee",
        "text_muted": "#a58f8f",
        "accent": "#e11d2e",
        "accent_hover": "#b91423",
        "grid": "#2c2121",
        "swatch": ["#0a0a0a", "#e11d2e"],
    },
    "claro": {
        "label": "Modo claro",
        "appearance": "light",
        "bg_app": "#f5f6fa",
        "bg_sidebar": "#ffffff",
        "bg_card": "#ffffff",
        "bg_card_hover": "#eef0f6",
        "bg_card_selected": "#d7cdfb",
        "border": "#c7cadb",
        "text_primary": "#1c1e2b",
        "text_muted": "#6b6f80",
        "accent": "#6d5ef1",
        "accent_hover": "#5843e6",
        "grid": "#e7e8f0",
        "swatch": ["#f5f6fa", "#6d5ef1"],
    },
    "azul": {
        "label": "Azul claro",
        "appearance": "light",
        "bg_app": "#eaf4fb",
        "bg_sidebar": "#dcedfa",
        "bg_card": "#ffffff",
        "bg_card_hover": "#d7ecfc",
        "bg_card_selected": "#ffd7ac",
        "border": "#9cc7e8",
        "text_primary": "#0f2a3d",
        "text_muted": "#4f7a94",
        "accent": "#ff8a3d",
        "accent_hover": "#f5730f",
        "grid": "#d7e9f5",
        "swatch": ["#cfe8fb", "#ff8a3d"],
    },
    "verde": {
        "label": "Verde claro",
        "appearance": "light",
        "bg_app": "#eaf7ee",
        "bg_sidebar": "#dcf2e3",
        "bg_card": "#ffffff",
        "bg_card_hover": "#d7f0df",
        "bg_card_selected": "#b9d3fb",
        "border": "#8fd6ae",
        "text_primary": "#123626",
        "text_muted": "#4f8a6c",
        "accent": "#2f6fed",
        "accent_hover": "#1f56c9",
        "grid": "#d3ecdd",
        "swatch": ["#cdeedb", "#2f6fed"],
    },
}

# Colores del indicador de subida/bajada. En temas claros el verde lima tiene que ser
# más oscuro: el lima brillante (#a3e635) casi no se lee sobre fondo blanco.
_CHANGE_COLORS = {"dark": ("#a3e635", "#f87171"), "light": ("#4d8a0a", "#d32f2f")}
for _theme in THEMES.values():
    _theme.setdefault("up", _CHANGE_COLORS[_theme["appearance"]][0])
    _theme.setdefault("down", _CHANGE_COLORS[_theme["appearance"]][1])
    # Botón de acción destructiva ("Sí, borrar"): rojo oscuro para que el texto
    # blanco se lea bien en cualquier tema; el aviso de advertencia en ámbar.
    _theme.setdefault("danger", "#c62828")
    _theme.setdefault("danger_hover", "#a61b1b")
    _theme.setdefault("warning", "#f59e0b")

# Paleta de colores para asignar a cada fondo (se reutiliza en orden cíclico)
COLOR_PALETTE = [
    "#e0245e",  # rosa/rojo (estilo de la captura de MyInvestor)
    "#2f7ed8",  # azul
    "#39b54a",  # verde
    "#f2a900",  # naranja
    "#8e44ad",  # morado
    "#16a085",  # turquesa
    "#e67e22",  # naranja oscuro
    "#c0392b",  # rojo oscuro
    "#2c3e50",  # gris azulado
    "#f1c40f",  # amarillo
]

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)
