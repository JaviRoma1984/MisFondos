import ctypes
import datetime as dt
import json
import os
import queue
import re
import sys
import threading
import tkinter as tk
import unicodedata
from tkinter import font as tkfont
from tkinter import messagebox

import customtkinter as ctk
import matplotlib
import matplotlib.dates as mdates
import pandas as pd
from PIL import Image, ImageColor, ImageDraw

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from . import alerts, applog, config, data_fetcher, fund_search, metrics, portfolio, settings, store, system, tray, users

PERIODS = ["1M", "3M", "6M", "YTD", "1A", "Todo"]
THEME_ORDER = ["oscuro", "rojo", "claro", "azul", "verde"]
UI_SCALING = 1.2
# Grosor de los bordes perimetrales de tarjetas, botones, campos y ventanas (px
# lógicos, se escalan con UI_SCALING y el DPI) y el de los elementos seleccionados.
BORDER_W = 2
BORDER_W_SELECTED = 3
SIDEBAR_W = 320
# Botón de usuario (entre "Mis fondos" y la rueda), solo con el nombre. CustomTkinter
# reserva a cada lado del contenido de un botón tanto margen como su radio de esquina,
# así que el hueco real para el nombre es: ancho − 2·radio − 2·borde − holgura.
USER_BTN_W = 100
TITLE_BTN_RADIUS = 12
USER_BTN_TEXT_W = USER_BTN_W - 2 * TITLE_BTN_RADIUS - 2 * BORDER_W - 6
USER_BTN_FONT = ("Segoe UI Semibold", 13)
# Ventana de configuración: ancho de la columna de colores y del texto explicativo
# de cada opción de la columna de inicio y reloj.
THEME_COL_W = 270
OPTION_TEXT_W = 270
# Hueco mínimo entre la barra de vistas (Fondo individual, Vista global…) y el
# recuadro de su derecha, y los anchos de ventana que lo respetan. La fila de los
# periodos + "Ver juntas 3 4 5 6" es la parte más ancha de la cabecera (~485 px).
HEADER_GAP = 60
WINDOW_W = 1320
WINDOW_MIN_W = 1240

ctk.set_default_color_theme("dark-blue")
ctk.set_widget_scaling(UI_SCALING)
ctk.set_window_scaling(UI_SCALING)

# La causa real del cuelgue al cambiar de tema: por defecto, cada vez que cambia el
# modo claro/oscuro, CustomTkinter OCULTA cada ventana viva (root y cualquier diálogo
# abierto) con withdraw(), bombea TODO el bucle de eventos con update() para pintar el
# color nativo de la barra de título de Windows, y 10ms después restaura el foco al
# widget que lo tenía antes. Ese update() puede disparar de forma reentrante nuestro
# propio código (el cambio de tema todavía se está ejecutando) y el restaurar-foco
# puede apuntar a un widget que para entonces ya se ha destruido — de ahí que la
# ventana "desaparezca" y el programa se cuelgue. Como coloreamos cada widget a mano,
# no necesitamos que Windows pinte la barra de título: se desactiva esa ruta entera.
ctk.CTk._deactivate_windows_window_header_manipulation = True
ctk.CTkToplevel._deactivate_windows_window_header_manipulation = True

FONT_TITLE = ("Segoe UI Semibold", 16)
FONT_SUBTITLE = ("Segoe UI", 12)
FONT_BODY = ("Segoe UI", 12)
FONT_SMALL = ("Segoe UI", 10)


def _apply_icon(win):
    """Pone el icono de monedas. Tiene que llamarse antes de 200ms desde que se crea
    la ventana: pasado ese tiempo CustomTkinter pone su propio icono por defecto,
    salvo que ya se haya llamado a iconbitmap() en esa ventana."""
    try:
        win.iconbitmap(config.ICON_FILE)
    except Exception:
        applog.log_exception("No se pudo poner el icono desde %s", config.ICON_FILE)


def _position_over_parent(win, master, width, height):
    """Centra una ventana secundaria sobre la ventana principal, para que
    aparezca en el mismo monitor que el programa (relevante con varias pantallas).

    El tamaño renderizado real no es solo `UI_SCALING`: CustomTkinter lo combina
    con el escalado de DPI que detecta del sistema operativo, así que hay que
    preguntarle a ScalingTracker el factor efectivo en vez de asumir el nuestro.
    """
    master.update_idletasks()
    effective_scaling = ctk.ScalingTracker.get_window_scaling(master)
    rendered_w = round(width * effective_scaling)
    rendered_h = round(height * effective_scaling)
    x = master.winfo_x() + (master.winfo_width() - rendered_w) // 2
    y = master.winfo_y() + (master.winfo_height() - rendered_h) // 2
    win.geometry(f"{width}x{height}+{x}+{y}")


VIEW_LABELS = {"individual": "Fondo individual", "global": "Vista global", "reparto": "Reparto",
               "rentabilidades": "Rentabilidades"}
# Vistas que no son una gráfica temporal: sin selector de periodos ni indicador.
SNAPSHOT_VIEWS = ("reparto", "rentabilidades")
# Vistas especiales "multi": las N primeras gráficas de la lista a la vez. Sus
# botones van en la barra de periodos, a continuación de los meses/años.
MULTI_COUNTS = (3, 4, 5, 6)

# Columnas de la tabla de rentabilidades: (clave, cabecera, ancho lógico). "YTD"
# se muestra como el año en curso; "name" es flexible y ocupa lo que sobre.
RETURN_COLUMNS = [
    ("1M", "1M", 62),
    ("3M", "3M", 62),
    ("YTD", "YTD", 62),
    ("1A", "1A", 62),
    ("3A", "3A anual.", 76),
    ("mine", "Mi rentabilidad", 100),
]

PERIOD_PHRASES = {
    "1M": "En 1 mes", "3M": "En 3 meses", "6M": "En 6 meses",
    "YTD": "En lo que va de año", "1A": "En 1 año", "Todo": "Desde el inicio",
}


def _fmt_es(value, decimals):
    """Número al estilo español: 44.587,81"""
    s = f"{value:,.{decimals}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _nav_decimals(value):
    return 2 if abs(value) >= 100 else 4


_CURRENCY_SYMBOLS = {"EUR": "€", "": "€", "USD": "$", "GBP": "£", "CHF": "CHF", "JPY": "¥"}


def _money(value, currency=""):
    return f"{_fmt_es(value, 2)} {_CURRENCY_SYMBOLS.get((currency or '').upper(), currency)}"


def _fit_text(widget, text, font, max_width):
    """Recorta `text` con "…" para que quepa en `max_width` px lógicos con `font`
    (tupla de fuente en px lógicos, como las de CustomTkinter)."""
    measure = tkfont.Font(root=widget, family=font[0], size=-abs(font[1])).measure
    if measure(text) <= max_width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:  # búsqueda binaria del prefijo más largo que cabe con "…"
        mid = (lo + hi + 1) // 2
        if measure(text[:mid].rstrip() + "…") <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "…"


class ConfirmDialog(ctk.CTkToplevel):
    """Confirmación de borrado con el mismo estilo que el resto del programa (la
    ventana estándar de Windows no sigue los colores del tema). "Cancelar" es el
    botón por defecto: Intro y Escape cancelan, para que un despiste nunca borre."""

    def __init__(self, parent, colors, title, message, confirm_text):
        super().__init__(parent)
        self.title(title)
        _apply_icon(self)
        self.result = False
        self._parent = parent
        c = colors
        self.configure(fg_color=c["bg_app"])
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        card = ctk.CTkFrame(self, fg_color=c["bg_card"], corner_radius=14, border_width=BORDER_W,
                            border_color=c["border"])
        card.pack(fill="both", expand=True, padx=16, pady=(16, 0))
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=18)
        ctk.CTkLabel(body, text="⚠", text_color=c["warning"], font=("Segoe UI Symbol", 30), width=44).pack(
            side="left", anchor="n")
        ctk.CTkLabel(body, text=message, text_color=c["text_primary"], font=FONT_BODY, justify="left",
                     anchor="w", wraplength=380).pack(side="left", fill="x", expand=True, padx=(12, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=16, pady=16)
        ctk.CTkButton(buttons, text=confirm_text, width=140, height=38, corner_radius=10,
                      fg_color=c["danger"], hover_color=c["danger_hover"], text_color="#ffffff",
                      font=("Segoe UI Semibold", 13), command=self._confirm).pack(side="right")
        self.cancel_button = ctk.CTkButton(
            buttons, text="Cancelar", width=120, height=38, corner_radius=10, fg_color="transparent",
            border_width=BORDER_W, border_color=c["accent"], text_color=c["text_primary"],
            hover_color=c["bg_card_hover"], font=("Segoe UI Semibold", 13), command=self._cancel)
        self.cancel_button.pack(side="right", padx=(0, 10))
        self.bind("<Return>", lambda _e: self._cancel())
        self.bind("<Escape>", lambda _e: self._cancel())

        self.update_idletasks()
        scaling = ctk.ScalingTracker.get_window_scaling(parent)
        _position_over_parent(self, parent, round(self.winfo_reqwidth() / scaling),
                              round(self.winfo_reqheight() / scaling))
        self.after(60, self.cancel_button.focus_set)

    def _confirm(self):
        self.result = True
        self._close()

    def _cancel(self):
        self.result = False
        self._close()

    def _close(self):
        parent = self._parent
        self.destroy()
        # Si quien preguntó es otro diálogo modal, Tk no le devuelve el grab solo.
        if isinstance(parent, ctk.CTkToplevel):
            try:
                parent.grab_set()
            except tk.TclError:
                pass


def _confirm_delete(title, message, parent, colors, confirm_text="Sí, borrar"):
    """Pregunta antes de cualquier borrado y espera la respuesta (True = borrar)."""
    dialog = ConfirmDialog(parent, colors, title, message, confirm_text)
    dialog.wait_window()
    return dialog.result


def _user_icon(color, size=64):
    """Silueta de usuario (cabeza + hombros) del color indicado, como imagen para
    CTkImage. Dibujada a 4x y reducida para que salga suave."""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rgb = ImageColor.getrgb(color)
    d.ellipse([s * 0.31, s * 0.08, s * 0.69, s * 0.46], fill=rgb)
    d.ellipse([s * 0.12, s * 0.54, s * 0.88, s * 1.30], fill=rgb)  # la parte de abajo queda fuera: hombros
    return img.resize((size, size), Image.LANCZOS)


def _sort_text(text):
    """Clave de orden alfabético sin tildes: si no, "Ábaco" va detrás de la "z"."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)).lower()


def _signed(value, text):
    return ("+" if value > 0 else "") + text


def _fmt_pct(pct, decimals=2):
    """-2.345 -> "−2,35 %" (con el signo menos tipográfico, que se lee mejor)."""
    sign = "−" if pct < 0 else "+" if pct > 0 else ""
    return f"{sign}{_fmt_es(abs(pct), decimals)} %"


def _alert_notification(new):
    """(mensaje, título) del aviso de Windows para las alertas recién saltadas."""
    if len(new) == 1:
        a = new[0]
        d = _nav_decimals(a["to_nav"])
        message = (f"{a['name']}: {_fmt_pct(a['pct'])} {alerts.KIND_TEXT[a['kind']]}\n"
                   f"Valor liquidativo {_fmt_es(a['from_nav'], d)} → {_fmt_es(a['to_nav'], d)} "
                   f"({dt.date.fromisoformat(a['to_date']):%d/%m})")
        return message, "MisFondos · Alerta de caída"
    lines = []
    for a in new:
        name = a["name"] if len(a["name"]) <= 30 else a["name"][:29].rstrip() + "…"
        lines.append(f"▼ {name}: {_fmt_pct(a['pct'])} {alerts.KIND_TEXT[a['kind']]}")
    return "\n".join(lines), f"MisFondos · {len(new)} alertas de caída"


def _portfolio_totals(funds):
    """Suma de toda la cartera (los fondos con aportaciones apuntadas), o None si
    no hay ninguno. Lo usan la franja de la vista global y el icono junto al reloj."""
    invested = value = 0.0
    with_movs = 0
    currencies = set()
    for f in funds:
        closes = data_fetcher.load_history(f["id"])["Close"].dropna()
        pos = portfolio.position(f["id"], closes)
        if pos is None or pos["value"] is None:
            continue
        with_movs += 1
        invested += pos["invested"]
        value += pos["value"]
        currencies.add((f.get("currency") or "EUR").upper())
    if not with_movs:
        return None
    gain = value - invested
    return {
        "invested": invested, "value": value, "gain": gain,
        "pct": gain / invested * 100 if invested > 0 else None,
        "currency": next(iter(currencies)) if len(currencies) == 1 else "EUR",
        "currencies": currencies, "funds": with_movs,
    }


def _fit_mpl_text(text_artist, full, max_px, renderer):
    """Como _fit_text, pero para un texto de matplotlib: lo deja escrito en
    `text_artist`, recortado con "…" para que mida como mucho `max_px` px."""
    text_artist.set_text(full)
    if text_artist.get_window_extent(renderer).width <= max_px:
        return
    lo, hi = 0, len(full)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        text_artist.set_text(full[:mid].rstrip() + "…")
        if text_artist.get_window_extent(renderer).width <= max_px:
            lo = mid
        else:
            hi = mid - 1
    text_artist.set_text(full[:lo].rstrip() + "…")


def _parse_es_number(text):
    """Acepta '1.500,50', '1500,5', '1500.5', '1.500' (miles) y '500 €'.
    Devuelve None si el campo está vacío; lanza ValueError si no es un número."""
    t = (text or "").strip().replace("€", "").replace(" ", "").replace(" ", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    return float(t)


class PillSwitch(ctk.CTkFrame):
    """Selector segmentado propio: marco redondeado con borde fino y, dentro, un
    botón por opción; la opción elegida es una píldora del color de acento.

    Sustituye a CTkSegmentedButton, que dibuja cada botón con su propio borde y
    rellena las esquinas entre botones con el color del borde (se ven "cuñas") y
    deja una rayita recta en el extremo. Aquí los botones van metidos `INSET` px
    hacia dentro para no pisar nunca las esquinas curvas del marco: la esquina del
    botón, (INSET, INSET), tiene que quedar dentro del arco interior del borde,
    es decir √2·(radio − INSET) < radio − BORDER_W. Con radio 10-12 y borde 2 → 5."""

    INSET = 5

    GAP = 2

    def __init__(self, master, colors, values, command=None, height=36, font=None, radius=12):
        fnt = font or FONT_SMALL
        # Ancho explícito medido del texto: con width=0 (autoajuste) CustomTkinter
        # deja una muesca en el borde derecho de la píldora. Las fuentes en tupla se
        # interpretan en píxeles lógicos, igual que width, así que escalan a la par.
        measure = tkfont.Font(root=master, family=fnt[0], size=-abs(fnt[1])).measure
        widths = [measure(v) + 26 for v in values]
        # El marco también con tamaño fijo (y sin pack_propagate): si crece solo para
        # abarcar los botones, CustomTkinter dibuja el rectángulo redondeado un poco
        # más estrecho que el widget real y en el extremo derecho sale un doble borde.
        # +2 de holgura por el redondeo del escalado de cada botón por separado.
        total_w = sum(widths) + 2 * self.INSET + self.GAP * (len(values) - 1) + 2
        super().__init__(master, fg_color=colors["bg_card"], corner_radius=radius,
                         border_width=BORDER_W, border_color=colors["border"], width=total_w, height=height)
        self.pack_propagate(False)
        self._colors = colors
        self._command = command
        self._value = None
        self._buttons = {}
        inner_h = height - 2 * self.INSET
        for i, value in enumerate(values):
            btn = ctk.CTkButton(
                self, text=value, width=widths[i], height=inner_h, corner_radius=max(radius - self.INSET, 4),
                border_width=0, fg_color="transparent", hover_color=colors["bg_card_hover"],
                text_color=colors["text_primary"], font=font or FONT_SMALL,
                command=lambda v=value: self._clicked(v),
            )
            btn.pack(side="left", padx=(self.INSET if i == 0 else self.GAP, 0), pady=self.INSET)
            self._buttons[value] = btn

    def _clicked(self, value):
        if value == self._value:
            return
        self.set(value)
        if self._command:
            self._command(value)

    def set(self, value):
        c = self._colors
        self._value = value
        for v, btn in self._buttons.items():
            selected = v == value
            btn.configure(
                fg_color=c["accent"] if selected else "transparent",
                hover_color=c["accent_hover"] if selected else c["bg_card_hover"],
                text_color="#ffffff" if selected else c["text_primary"],
            )

    def get(self):
        return self._value


def _shade(color, amount):
    """Oscurece un color "#rrggbb" mezclándolo con negro (amount de 0 a 1)."""
    return tuple(round(v * (1 - amount)) for v in ImageColor.getrgb(color)[:3])


class ToggleSwitch(ctk.CTkLabel):
    """Interruptor de sí/no dibujado a mano (con PIL, suavizado). El CTkSwitch de
    CustomTkinter no deja poner borde al círculo que se desliza, y en algunos temas
    (el blanco sobre el naranja de "Azul claro", o sobre las pistas grises claras)
    apenas se distinguía. Aquí pista y círculo llevan un borde oscuro del mismo tono
    que la pista, que lo recorta bien en cualquier combinación de colores."""

    W, H = 46, 24     # tamaño lógico (se escala como el resto de la interfaz)
    INSET = 3         # margen entre el círculo y el borde de la pista
    EDGE = 1.5        # grosor de los bordes
    SUPERSAMPLE = 4   # se dibuja a 4x y se reduce: bordes suaves, sin dientes de sierra

    def __init__(self, master, colors, value=False, command=None, enabled=True):
        self._colors = colors
        self._value = bool(value)
        self._command = command
        self._enabled = enabled
        scale = ctk.ScalingTracker.get_widget_scaling(master)
        self._images = {v: self._render(v, scale) for v in (False, True)}
        super().__init__(master, text="", image=self._images[self._value], width=self.W, height=self.H,
                         cursor="hand2" if enabled else "arrow")
        if enabled:
            self.bind("<ButtonRelease-1>", lambda _e: self.toggle())

    def _render(self, on, scale):
        c = self._colors
        track = ImageColor.getrgb(c["accent"] if on else c["text_muted"])[:3]
        edge = _shade(c["accent"] if on else c["text_muted"], 0.45)
        s = self.SUPERSAMPLE
        w, h = round(self.W * scale), round(self.H * scale)
        img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        edge_w = max(1, round(self.EDGE * scale * s))
        draw.rounded_rectangle([0, 0, w * s - 1, h * s - 1], radius=h * s / 2,
                               fill=track + (255,), outline=edge + (255,), width=edge_w)
        inset = round(self.INSET * scale * s)
        diameter = h * s - 2 * inset
        x0 = w * s - inset - diameter if on else inset
        draw.ellipse([x0, inset, x0 + diameter, inset + diameter],
                     fill=(255, 255, 255, 255), outline=edge + (255,), width=edge_w)
        img = img.resize((w, h), Image.LANCZOS)
        if not self._enabled:  # desactivado: medio transparente
            img.putalpha(img.getchannel("A").point(lambda a: round(a * 0.45)))
        return ctk.CTkImage(light_image=img, dark_image=img, size=(self.W, self.H))

    def get(self):
        return self._value

    def set(self, value):
        self._value = bool(value)
        self.configure(image=self._images[self._value])

    def toggle(self):
        if not self._enabled:
            return
        self.set(not self._value)
        if self._command:
            self._command(self)


class Tooltip:
    """Bocadillo de ayuda que aparece al dejar el puntero sobre un botón y desaparece
    al quitarlo (o al pulsarlo).

    CTkButton.bind() engancha el evento a sus widgets internos (lienzo, texto e
    icono), así que al mover el puntero de uno a otro DENTRO del mismo botón llegan
    <Leave> y <Enter> seguidos: antes de ocultar se comprueba si el puntero sigue
    dentro del rectángulo del botón, para que no parpadee."""

    DELAY_MS = 350

    def __init__(self, widget, text, colors):
        self.widget = widget
        self.text = text
        self.colors = colors
        self._tip = None
        self._after_id = None
        widget.bind("<Enter>", self._on_enter, add=True)
        widget.bind("<Leave>", self._on_leave, add=True)
        widget.bind("<ButtonPress-1>", lambda _e: self.hide(), add=True)

    def _pointer_inside(self):
        try:
            x, y = self.widget.winfo_pointerxy()
            wx, wy = self.widget.winfo_rootx(), self.widget.winfo_rooty()
            return wx <= x < wx + self.widget.winfo_width() and wy <= y < wy + self.widget.winfo_height()
        except tk.TclError:
            return False

    def _on_enter(self, _event):
        if self._tip is None and self._after_id is None:
            self._after_id = self.widget.after(self.DELAY_MS, self._show)

    def _on_leave(self, _event):
        try:
            self.widget.after(40, self._hide_if_outside)
        except tk.TclError:
            pass

    def _hide_if_outside(self):
        if not self._pointer_inside():
            self.hide()

    def _show(self):
        self._after_id = None
        try:
            if not self.widget.winfo_exists() or not self._pointer_inside():
                return
        except tk.TclError:
            return
        c = self.colors
        tip = tk.Toplevel(self.widget)  # hijo del botón: si el botón se destruye, se va con él
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.configure(bg=c["border"])
        tk.Label(tip, text=self.text, bg=c["bg_card_hover"], fg=c["text_primary"], font=("Segoe UI", 10),
                 padx=10, pady=5, justify="left").pack(padx=2, pady=2)  # 2 px de borde del tema
        tip.update_idletasks()
        w = tip.winfo_width()
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2 - w // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        # Que no se salga de la ventana en la que está el botón (y así tampoco de su monitor).
        win = self.widget.winfo_toplevel()
        left, right = win.winfo_rootx() + 4, win.winfo_rootx() + win.winfo_width() - 4
        x = max(left, min(x, right - w))
        tip.geometry(f"+{x}+{y}")
        self._tip = tip

    def hide(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


def _parse_date(text):
    t = (text or "").strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Fecha no válida: '{t}'. Usa el formato dd/mm/aaaa")


def _period_start(df, period):
    if df.empty:
        return None
    last_date = df.index.max()
    if period == "1M":
        return last_date - dt.timedelta(days=30)
    if period == "3M":
        return last_date - dt.timedelta(days=91)
    if period == "6M":
        return last_date - dt.timedelta(days=182)
    if period == "YTD":
        return dt.datetime(last_date.year, 1, 1)
    if period == "1A":
        return last_date - dt.timedelta(days=365)
    return df.index.min()


class AddFundDialog(ctk.CTkToplevel):
    def __init__(self, master, colors, on_added):
        super().__init__(master)
        self.title("Añadir fondo")
        _apply_icon(self)
        self.configure(fg_color=colors["bg_app"])
        self.colors = colors
        self.on_added = on_added
        self.candidates = []
        self.selected_index = None
        self.result_buttons = []

        self.transient(master)
        self.grab_set()

        c = colors
        ctk.CTkLabel(self, text="Añadir fondo indexado", font=FONT_TITLE, text_color=c["text_primary"]).pack(
            anchor="w", padx=20, pady=(20, 4)
        )
        ctk.CTkLabel(
            self, text="Busca por ISIN (lo encuentras en la ficha del fondo en MyInvestor)",
            font=FONT_SMALL, text_color=c["text_muted"],
        ).pack(anchor="w", padx=20)

        search_row = ctk.CTkFrame(self, fg_color="transparent")
        search_row.pack(fill="x", padx=20, pady=(10, 0))
        self.isin_entry = ctk.CTkEntry(
            search_row, placeholder_text="p.ej. IE00B3XXRP09", font=FONT_BODY, height=38,
            border_width=BORDER_W, border_color=c["border"],
        )
        self.isin_entry.pack(side="left", fill="x", expand=True)
        self.isin_entry.bind("<Return>", lambda _e: self._do_search())
        ctk.CTkButton(
            search_row, text="Buscar", width=90, height=38, fg_color=c["accent"], hover_color=c["accent_hover"],
            command=self._do_search,
        ).pack(side="left", padx=(8, 0))

        ctk.CTkLabel(self, text="Resultados", font=FONT_SMALL, text_color=c["text_muted"]).pack(
            anchor="w", padx=20, pady=(16, 4)
        )
        self.results_frame = ctk.CTkScrollableFrame(
            self, fg_color=c["bg_card"], height=180, corner_radius=12,
            border_width=BORDER_W, border_color=c["border"],
        )
        self.results_frame.pack(fill="both", expand=True, padx=20)

        ctk.CTkLabel(self, text="Nombre a mostrar (opcional)", font=FONT_SMALL, text_color=c["text_muted"]).pack(
            anchor="w", padx=20, pady=(14, 4)
        )
        self.name_entry = ctk.CTkEntry(
            self, placeholder_text="Se usa el nombre encontrado si lo dejas vacío", height=36,
            border_width=BORDER_W, border_color=c["border"],
        )
        self.name_entry.pack(fill="x", padx=20)

        ctk.CTkButton(
            self, text="+  Añadir fondo seleccionado", height=42, corner_radius=10,
            fg_color=c["accent"], hover_color=c["accent_hover"], font=("Segoe UI Semibold", 13),
            command=self._do_add,
        ).pack(fill="x", padx=20, pady=20)

        # El tamaño se calcula a partir del contenido ya empaquetado (en vez de un
        # "440x480" fijo) para que nunca se recorte un botón, aunque cambien las
        # fuentes o el escalado de la interfaz.
        self.update_idletasks()
        scaling = ctk.ScalingTracker.get_window_scaling(master)
        req_w = round(self.winfo_reqwidth() / scaling)
        req_h = round(self.winfo_reqheight() / scaling)
        _position_over_parent(self, master, req_w, req_h)

    def _do_search(self):
        # Sin espacios intermedios: al copiar el ISIN de la web a veces viene "ES01 4007 2028".
        isin = "".join(self.isin_entry.get().split()).upper()
        if not isin:
            return
        c = self.colors
        for w in self.results_frame.winfo_children():
            w.destroy()
        self.result_buttons = []
        self.selected_index = None

        searching = ctk.CTkLabel(self.results_frame, text="Buscando...", text_color=c["text_muted"], font=FONT_SMALL)
        searching.pack(anchor="w", padx=8, pady=8)
        self.update_idletasks()

        try:
            self.candidates = fund_search.search_by_isin(isin)
        except Exception:  # noqa: BLE001
            applog.log_exception("Fallo en la búsqueda de %s", isin)
            searching.destroy()
            messagebox.showerror(
                "Error de búsqueda",
                "No se ha podido conectar con el servicio de cotizaciones. Revisa la conexión e inténtalo de nuevo.",
            )
            return
        searching.destroy()

        if not self.candidates:
            ctk.CTkLabel(
                self.results_frame, text="Sin resultados para ese ISIN, revisa que esté bien escrito",
                text_color=c["text_muted"], font=FONT_SMALL,
            ).pack(anchor="w", padx=8, pady=8)
            return

        ctk.CTkLabel(
            self.results_frame,
            text="El código de la derecha es el identificador interno\nde Yahoo para este ISIN: es el mismo fondo.",
            text_color=c["text_muted"], font=FONT_SMALL, justify="left",
        ).pack(anchor="w", padx=8, pady=(4, 6))

        for i, cand in enumerate(self.candidates):
            row = ctk.CTkButton(
                self.results_frame,
                text=f"{cand['name']}   —   {cand['symbol']} ({cand['exchange']})",
                anchor="w", height=36, corner_radius=8,
                fg_color=c["bg_card_hover"], hover_color=c["bg_card_selected"],
                text_color=c["text_primary"], font=FONT_SMALL,
                border_width=BORDER_W, border_color=c["border"],
                command=lambda idx=i: self._select_candidate(idx),
            )
            row.pack(fill="x", pady=3, padx=2)
            self.result_buttons.append(row)

        if len(self.candidates) == 1:
            self._select_candidate(0)

    def _select_candidate(self, idx):
        c = self.colors
        self.selected_index = idx
        for i, btn in enumerate(self.result_buttons):
            btn.configure(fg_color=c["bg_card_selected"] if i == idx else c["bg_card_hover"])

    def _do_add(self):
        if self.selected_index is None or not self.candidates:
            messagebox.showwarning("Selecciona un resultado", "Primero busca y selecciona un fondo de la lista.")
            return
        isin = self.isin_entry.get().strip().upper()
        chosen = self.candidates[self.selected_index]
        name = self.name_entry.get().strip() or chosen["name"]

        # Un mismo ISIN puede cotizar en varias bolsas/plataformas; algunas no tienen
        # histórico en Yahoo aunque aparezcan en la búsqueda. Se prueba primero el
        # resultado elegido y, si no tiene datos, se prueba con los demás en silencio
        # en vez de dar un error sin salida (el usuario no puede saber de antemano
        # cuál de los resultados tiene datos).
        ordered = [chosen] + [c for i, c in enumerate(self.candidates) if i != self.selected_index]
        df = None
        used_candidate = None
        for candidate in ordered:
            try:
                trial_df = data_fetcher.fetch_initial_history(candidate["symbol"])
            except Exception:  # noqa: BLE001
                applog.log_exception("Fallo al descargar histórico de %s", candidate["symbol"])
                continue
            if not trial_df.empty:
                df = trial_df
                used_candidate = candidate
                break

        if df is None:
            messagebox.showerror(
                "Sin datos",
                "No se ha podido obtener histórico para ese fondo en ninguna de sus cotizaciones encontradas.",
            )
            return

        try:
            fund = store.add_fund(name, isin, used_candidate["symbol"], currency=df.attrs.get("currency", ""))
        except ValueError as exc:
            messagebox.showerror("Fondo ya existe", str(exc))
            return

        data_fetcher.save_history(fund["id"], df)
        applog.info("Fondo añadido: %s (%s, ticker=%s)", name, isin, used_candidate["symbol"])
        self.on_added(fund)
        self.destroy()


class ThemeRow(ctk.CTkFrame):
    def __init__(self, master, colors, theme_key, theme_def, selected, on_click):
        super().__init__(
            master,
            fg_color=colors["bg_card_selected"] if selected else colors["bg_card_hover"],
            corner_radius=12, width=THEME_COL_W, height=56,
            border_width=BORDER_W_SELECTED if selected else BORDER_W, border_color=colors["accent"] if selected else colors["border"],
        )
        self.pack_propagate(False)

        swatch_frame = ctk.CTkFrame(self, fg_color="transparent", width=44, height=32)
        swatch_frame.pack(side="left", padx=(14, 12), pady=10)
        swatch_frame.pack_propagate(False)
        ctk.CTkFrame(
            swatch_frame, fg_color=theme_def["swatch"][0], width=22, height=32, corner_radius=8,
            border_width=BORDER_W, border_color=colors["border"],
        ).pack(side="left")
        ctk.CTkFrame(
            swatch_frame, fg_color=theme_def["swatch"][1], width=22, height=32, corner_radius=8,
            border_width=BORDER_W, border_color=colors["border"],
        ).pack(side="left", padx=(2, 0))

        label = ctk.CTkLabel(self, text=theme_def["label"], text_color=colors["text_primary"], font=FONT_BODY, anchor="w")
        label.pack(side="left", fill="x", expand=True)

        check = ctk.CTkLabel(
            self, text="✓" if selected else "", text_color=colors["accent"], font=("Segoe UI Semibold", 15), width=30
        )
        check.pack(side="right", padx=(0, 14))

        # <ButtonRelease-1>, no <Button-1>: el clic dispara una reconstrucción que
        # destruye esta misma fila. Si se disparara en la pulsación (Button-1), la
        # fila podía quedar destruida mientras el botón del ratón seguía físicamente
        # abajo, y al soltarlo Tk intentaba repartir el ButtonRelease sobre un widget
        # que ya no existía — eso es lo que colgaba la app. En la liberación, el
        # gesto de clic ya ha terminado del todo sobre este widget.
        for widget in (self, swatch_frame, label, check):
            widget.bind("<ButtonRelease-1>", lambda _e: on_click(theme_key))


class SettingsDialog(ctk.CTkToplevel):
    """Colores, inicio/reloj y alertas de caídas, en tres columnas (en una sola
    saldría más alta que la pantalla de un portátil). Aplica cada tema al elegirlo,
    pero no se cierra sola: el usuario la cierra con "Cerrar" cuando ya ha decidido
    la combinación definitiva."""

    def __init__(self, master, app):
        super().__init__(master)
        self.title("Configuración")
        _apply_icon(self)
        self.app = app

        self.transient(master)
        self.grab_set()

        self._render()

        # Tamaño ajustado al contenido real (ver AddFundDialog); se calcula una sola
        # vez aquí, no en cada _render(), para que el diálogo no salte de posición
        # cada vez que el usuario prueba un tema.
        self.update_idletasks()
        scaling = ctk.ScalingTracker.get_window_scaling(master)
        req_w = round(self.winfo_reqwidth() / scaling)
        req_h = round(self.winfo_reqheight() / scaling)
        _position_over_parent(self, master, req_w, req_h)

    def _render(self):
        for w in self.winfo_children():
            w.destroy()

        c = self.app.colors
        self.configure(fg_color=c["bg_app"])

        ctk.CTkLabel(self, text="Configuración", font=FONT_TITLE, text_color=c["text_primary"]).pack(
            anchor="w", padx=20, pady=(20, 10)
        )
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20)

        # --- columna izquierda: colores ---
        rows_frame = ctk.CTkFrame(body, fg_color="transparent")
        rows_frame.pack(side="left", fill="y", anchor="n")
        self._section(rows_frame, "Colores", "Se aplican al momento al elegirlos")
        for key in THEME_ORDER:
            theme_def = config.THEMES[key]
            row = ThemeRow(
                rows_frame, c, key, theme_def,
                selected=(key == self.app.theme_name),
                on_click=self._select,
            )
            row.pack(fill="x", pady=5)

        # --- columna derecha: inicio y reloj ---
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="left", fill="y", anchor="n", padx=(24, 0))
        self._section(right, "Inicio y reloj", "MisFondos junto al reloj de Windows")
        card = ctk.CTkFrame(right, fg_color=c["bg_card"], corner_radius=12,
                            border_width=BORDER_W, border_color=c["border"])
        card.pack(fill="x", pady=5)
        supported = system.autostart_supported()
        self._option(
            card, "Arrancar con Windows",
            "Se abre solo al encender el ordenador, escondido junto al reloj, y mantiene "
            "tus fondos al día." if supported else
            "Solo disponible en el programa instalado.",
            system.is_autostart_enabled(), self._toggle_autostart, enabled=supported,
        )
        ctk.CTkFrame(card, fg_color=c["border"], height=BORDER_W, corner_radius=0).pack(fill="x", padx=14)
        self._option(
            card, "La X lo deja junto al reloj",
            "Al cerrar la ventana sigue funcionando y actualizando. Para salir del todo: "
            "clic derecho en su icono del reloj → Salir.",
            settings.get_close_to_tray(), self._toggle_close_to_tray,
        )

        # --- tercera columna: alertas de caídas (del usuario activo) ---
        third = ctk.CTkFrame(body, fg_color="transparent")
        third.pack(side="left", fill="y", anchor="n", padx=(24, 0))
        user = users.current()
        self._section(third, "Alertas de caídas",
                      _fit_text(self, f"Avisos de Windows para «{user['name']}»" if user else "Avisos de Windows",
                                FONT_SMALL, OPTION_TEXT_W))
        card = ctk.CTkFrame(third, fg_color=c["bg_card"], corner_radius=12,
                            border_width=BORDER_W, border_color=c["border"])
        card.pack(fill="x", pady=5)
        rules = settings.get_alerts()
        self._alert_option(card, alerts.DAY, "Caída en un día", "Último valor frente al anterior. Avisa si baja:",
                           rules[alerts.DAY])
        ctk.CTkFrame(card, fg_color=c["border"], height=BORDER_W, corner_radius=0).pack(fill="x", padx=14)
        self._alert_option(card, alerts.WEEK, "Caída en una semana", "Frente al valor de hace 7 días. Avisa si baja:",
                           rules[alerts.WEEK])
        ctk.CTkFrame(card, fg_color=c["border"], height=BORDER_W, corner_radius=0).pack(fill="x", padx=14)
        footer = ctk.CTkFrame(card, fg_color="transparent")
        footer.pack(fill="x", padx=14, pady=12)
        self.test_button = ctk.CTkButton(
            footer, text="Enviar aviso de prueba", height=34, corner_radius=10, fg_color="transparent",
            border_width=BORDER_W, border_color=c["border"], text_color=c["text_primary"],
            hover_color=c["bg_card_hover"], font=FONT_SMALL, command=self._send_test_alert)
        self.test_button.pack(fill="x")
        ctk.CTkLabel(footer, text=self._last_alerts_text(), font=FONT_SMALL, text_color=c["text_muted"],
                     anchor="w", justify="left").pack(fill="x", pady=(10, 0))

        ctk.CTkButton(
            self, text="Cerrar", height=38, corner_radius=10, fg_color="transparent",
            border_width=BORDER_W, border_color=c["border"], text_color=c["text_muted"], hover_color=c["bg_card_hover"],
            command=self.destroy,
        ).pack(fill="x", padx=20, pady=20)

    def _section(self, parent, title, subtitle):
        c = self.app.colors
        ctk.CTkLabel(parent, text=title, font=("Segoe UI Semibold", 13), text_color=c["text_primary"],
                     anchor="w").pack(fill="x")
        ctk.CTkLabel(parent, text=subtitle, font=FONT_SMALL, text_color=c["text_muted"],
                     anchor="w").pack(fill="x", pady=(0, 6))

    def _option(self, parent, title, description, value, on_change, enabled=True):
        """Una opción de sí/no: título e interruptor en una línea, explicación debajo."""
        c = self.app.colors
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=title, font=FONT_BODY, anchor="w",
                     text_color=c["text_primary"] if enabled else c["text_muted"]).pack(side="left")
        ToggleSwitch(top, c, value, command=on_change, enabled=enabled).pack(side="right")
        ctk.CTkLabel(row, text=description, font=FONT_SMALL, text_color=c["text_muted"], anchor="w",
                     justify="left", wraplength=OPTION_TEXT_W).pack(fill="x", pady=(4, 0))

    def _alert_option(self, parent, kind, title, description, rule):
        """Regla de alerta: título e interruptor, explicación y umbral a elegir."""
        c = self.app.colors
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=title, font=FONT_BODY, anchor="w", text_color=c["text_primary"]).pack(side="left")
        ToggleSwitch(top, c, rule["on"], command=lambda sw: self._set_alert(kind, on=sw.get())).pack(side="right")
        ctk.CTkLabel(row, text=description, font=FONT_SMALL, text_color=c["text_muted"], anchor="w",
                     justify="left", wraplength=OPTION_TEXT_W).pack(fill="x", pady=(4, 8))
        pills = PillSwitch(row, c, [f"{p} %" for p in alerts.OPTIONS[kind]],
                           command=lambda value: self._set_alert(kind, pct=int(value.split()[0])),
                           height=34, font=FONT_SMALL, radius=10)
        pills.set(f"{rule['pct']} %")
        pills.pack(anchor="w")

    @staticmethod
    def _set_alert(kind, on=None, pct=None):
        settings.set_alert(kind, on=on, pct=pct)
        applog.info("Alerta %s: %s", kind, settings.get_alerts()[kind])

    def _last_alerts_text(self):
        recent = alerts.history()[:3]
        if not recent:
            return "Todavía no ha saltado ningún aviso."
        lines = ["Últimos avisos:"]
        for a in recent:
            when = dt.date.fromisoformat(a["to_date"]).strftime("%d/%m")
            tail = f" {_fmt_pct(a['pct'])} ({'día' if a['kind'] == alerts.DAY else 'semana'})"
            name = _fit_text(self, a["name"], FONT_SMALL, OPTION_TEXT_W - 130)
            lines.append(f"{when} · {name}{tail}")
        return "\n".join(lines)

    def _send_test_alert(self):
        if not self.app.tray.running:
            self.test_button.configure(text="Sin icono junto al reloj: no se puede avisar")
            return
        self.app.tray.notify(
            "Así se verán los avisos cuando un fondo baje más de lo que has elegido. "
            "Si no te ha aparecido, revisa que Windows no tenga activado «No molestar».",
            "MisFondos · Aviso de prueba")
        applog.info("Aviso de prueba enviado")
        self.test_button.configure(text="Aviso enviado ✓")
        self.after(2500, lambda: self.test_button.winfo_exists() and
                   self.test_button.configure(text="Enviar aviso de prueba"))

    def _toggle_autostart(self, switch):
        try:
            system.set_autostart(switch.get())
            applog.info("Arranque con Windows %s", "activado" if switch.get() else "desactivado")
        except OSError:
            applog.log_exception("No se pudo cambiar el arranque con Windows")
            switch.set(system.is_autostart_enabled())  # el interruptor muestra lo que hay de verdad

    def _toggle_close_to_tray(self, switch):
        settings.set_close_to_tray(switch.get())
        applog.info("La X %s", "lo deja junto al reloj" if switch.get() else "cierra del todo")

    def _select(self, theme_key):
        # Nunca se destruye nada aquí dentro: este método corre DENTRO del manejador
        # de clic de la propia fila que el usuario ha pulsado, y _render() destruye
        # esa misma fila para reconstruir el diálogo. Tkinter no lleva bien que un
        # widget se destruya en mitad de su propio evento (ButtonRelease pendiente
        # sobre un widget ya inexistente) — de ahí el cuelgue. Se aplaza todo el
        # trabajo real a la siguiente vuelta del bucle de eventos con after(), y se
        # ignora un segundo clic mientras el primero todavía se está aplicando.
        if getattr(self, "_switching", False):
            return
        self._switching = True
        self.after(30, lambda: self._apply_and_render(theme_key))

    def _apply_and_render(self, theme_key):
        try:
            # Se suelta el grab modal antes de tocar la ventana principal: mantenerlo
            # mientras se destruyen widgets de otra ventana es lo que colgaba la app.
            try:
                self.grab_release()
            except Exception:
                pass
            self.app._apply_theme(theme_key)
            self._render()
        except Exception:
            applog.log_exception("Fallo al cambiar de tema a %s", theme_key)
        finally:
            self._switching = False
            try:
                self.grab_set()
            except Exception:
                pass


class PortfolioDialog(ctk.CTkToplevel):
    """Aportaciones y reembolsos de un fondo. Los cambios se reflejan al momento en
    la franja de la ventana principal y en las marcas de la gráfica."""

    def __init__(self, master, app, fund):
        super().__init__(master)
        self.title("Mis aportaciones")
        _apply_icon(self)
        self.app = app
        self.fund = fund
        self.colors = c = app.colors
        self.currency = fund.get("currency", "")
        self.configure(fg_color=c["bg_app"])
        self.transient(master)
        self.grab_set()

        ctk.CTkLabel(self, text="Mis aportaciones", font=FONT_TITLE, text_color=c["text_primary"]).pack(
            anchor="w", padx=20, pady=(20, 0))
        ctk.CTkLabel(self, text=fund["name"], font=FONT_SMALL, text_color=c["text_muted"]).pack(anchor="w", padx=20)

        form = ctk.CTkFrame(self, fg_color=c["bg_card"], corner_radius=12, border_width=BORDER_W, border_color=c["border"])
        form.pack(fill="x", padx=20, pady=(14, 0))
        grid = ctk.CTkFrame(form, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(12, 4))

        def field(col, caption, placeholder, width):
            ctk.CTkLabel(grid, text=caption, font=FONT_SMALL, text_color=c["text_muted"]).grid(
                row=0, column=col, sticky="w", padx=(0, 12))
            entry = ctk.CTkEntry(grid, placeholder_text=placeholder, width=width, height=34,
                                 border_width=BORDER_W, border_color=c["border"])
            entry.grid(row=1, column=col, sticky="w", padx=(0, 12))
            entry.bind("<Return>", lambda _e: self._add())
            return entry

        self.date_entry = field(0, "Fecha", "dd/mm/aaaa", 120)
        self.date_entry.insert(0, dt.date.today().strftime("%d/%m/%Y"))
        symbol = _CURRENCY_SYMBOLS.get((self.currency or "").upper(), self.currency)
        self.amount_entry = field(1, f"Importe ({symbol})", "p.ej. 500,00", 130)
        self.units_entry = field(2, "Participaciones (opcional)", "se calculan solas", 160)

        ctk.CTkLabel(grid, text="Tipo", font=FONT_SMALL, text_color=c["text_muted"]).grid(row=0, column=3, sticky="w")
        self.kind_switch = PillSwitch(grid, c, ["Aportación", "Reembolso"], height=36, radius=10)
        self.kind_switch.set("Aportación")
        self.kind_switch.grid(row=1, column=3, sticky="w")

        ctk.CTkLabel(
            form, text="Si no indicas participaciones, se calculan con el valor liquidativo de esa fecha. "
                       "Si las copias de MyInvestor, el cálculo es exacto.",
            font=FONT_SMALL, text_color=c["text_muted"], wraplength=640, justify="left",
        ).pack(anchor="w", padx=14)
        ctk.CTkButton(
            form, text="+  Añadir movimiento", width=240, height=38, corner_radius=10,
            fg_color=c["accent"], hover_color=c["accent_hover"], font=("Segoe UI Semibold", 13),
            command=self._add,
        ).pack(anchor="w", padx=14, pady=(8, 12))

        ctk.CTkLabel(self, text="Movimientos", font=FONT_SMALL, text_color=c["text_muted"]).pack(
            anchor="w", padx=20, pady=(14, 4))
        self.list_frame = ctk.CTkScrollableFrame(
            self, fg_color=c["bg_card"], height=200, corner_radius=12, border_width=BORDER_W, border_color=c["border"])
        self.list_frame.pack(fill="both", expand=True, padx=20)

        self.summary = ctk.CTkLabel(self, text="", font=FONT_BODY, text_color=c["text_primary"], justify="left")
        self.summary.pack(anchor="w", padx=20, pady=(10, 0))

        ctk.CTkButton(
            self, text="Cerrar", height=38, corner_radius=10, fg_color="transparent",
            border_width=BORDER_W, border_color=c["border"], text_color=c["text_muted"], hover_color=c["bg_card_hover"],
            command=self.destroy,
        ).pack(fill="x", padx=20, pady=16)

        self._render_list()
        self.update_idletasks()
        scaling = ctk.ScalingTracker.get_window_scaling(master)
        _position_over_parent(self, master, round(self.winfo_reqwidth() / scaling),
                              round(self.winfo_reqheight() / scaling))
        self.after(50, self.amount_entry.focus_set)

    def _closes(self):
        return data_fetcher.load_history(self.fund["id"])["Close"].dropna()

    def _add(self):
        try:
            when = _parse_date(self.date_entry.get())
            if when > dt.date.today():
                raise ValueError("La fecha no puede ser posterior a hoy.")
            amount = _parse_es_number(self.amount_entry.get())
            if amount is None:
                raise ValueError("Indica el importe.")
            units = _parse_es_number(self.units_entry.get())
        except ValueError as exc:
            messagebox.showerror("Dato no válido", str(exc).replace("could not convert string to float",
                                                                    "Número no válido"), parent=self)
            return
        kind = portfolio.APORTACION if self.kind_switch.get() == "Aportación" else portfolio.REEMBOLSO
        closes = self._closes()
        if units is None and portfolio.nav_on(closes, when) is None:
            first = closes.index.min()
            desde = f" (el histórico descargado empieza el {first:%d/%m/%Y})" if not closes.empty else ""
            messagebox.showerror(
                "Sin valor liquidativo",
                f"No hay valor liquidativo para esa fecha{desde}. Indica las participaciones a mano.",
                parent=self)
            return
        if kind == portfolio.REEMBOLSO:
            pos = portfolio.position(self.fund["id"], closes)
            held = pos["units"] if pos else 0.0
            wanted = units if units is not None else amount / portfolio.nav_on(closes, when)
            if wanted > held + 1e-6:
                messagebox.showerror(
                    "Reembolso mayor que la posición",
                    f"Ese reembolso son {_fmt_es(wanted, 4)} participaciones y solo tienes "
                    f"{_fmt_es(held, 4)} apuntadas.", parent=self)
                return
        try:
            mov = portfolio.add_movement(self.fund["id"], when, kind, amount, units)
        except ValueError as exc:
            messagebox.showerror("Dato no válido", str(exc), parent=self)
            return
        applog.info("Movimiento añadido en %s: %s", self.fund["id"], mov)
        self.amount_entry.delete(0, "end")
        self.units_entry.delete(0, "end")
        self._render_list()
        self.app._redraw()

    def _delete(self, mov):
        if not _confirm_delete(
                "Borrar movimiento",
                f"¿Seguro que quieres borrar el movimiento del {dt.date.fromisoformat(mov['date']):%d/%m/%Y} "
                f"de {_money(mov['amount'], self.currency)}?", parent=self, colors=self.colors):
            return
        portfolio.remove_movement(self.fund["id"], mov["id"])
        applog.info("Movimiento borrado en %s: %s", self.fund["id"], mov)
        # La fila (y su botón ✕, que es quien nos está llamando) se destruye al
        # re-pintar la lista: se aplaza para no destruirlo dentro de su propio clic.
        self.after(30, self._after_delete)

    def _after_delete(self):
        if self.winfo_exists():
            self._render_list()
        self.app._redraw()

    def _render_list(self):
        c = self.colors
        for w in self.list_frame.winfo_children():
            w.destroy()
        closes = self._closes()
        movs = portfolio.movements(self.fund["id"])
        if not movs:
            ctk.CTkLabel(self.list_frame, text="Aún no hay movimientos apuntados.",
                         font=FONT_SMALL, text_color=c["text_muted"]).pack(anchor="w", padx=8, pady=8)
        for mov in reversed(movs):  # los más recientes arriba
            row = ctk.CTkFrame(self.list_frame, fg_color=c["bg_card_hover"], corner_radius=8,
                               border_width=BORDER_W, border_color=c["border"])
            row.pack(fill="x", pady=3, padx=2)
            is_aport = mov["kind"] == portfolio.APORTACION
            units, src = portfolio.movement_units(mov, closes)
            units_txt = "sin VL" if units is None else f"{_fmt_es(units, 4)} part." + (
                " (calculadas)" if src == "calculado" else "")
            # La ✕ se empaqueta ANTES que las columnas: pack reparte el espacio por orden,
            # y si va la última las columnas de ancho fijo se lo comen todo y no se ve.
            delete_btn = ctk.CTkButton(
                row, text="✕", width=30, height=26, corner_radius=6, fg_color="transparent",
                hover_color=c["bg_card_selected"], text_color=c["text_muted"], font=FONT_SMALL,
                command=lambda m=mov: self._delete(m),
            )
            delete_btn.pack(side="right", padx=8)
            Tooltip(delete_btn, "Borrar este movimiento (pide confirmación)", c)
            cells = (
                (f"{dt.date.fromisoformat(mov['date']):%d/%m/%Y}", c["text_primary"], 90),
                ("▲ Aportación" if is_aport else "▼ Reembolso", c["up"] if is_aport else c["down"], 110),
                (_money(mov["amount"], self.currency), c["text_primary"], 110),
                (units_txt, c["text_muted"], 190),
            )
            for text, color, width in cells:
                ctk.CTkLabel(row, text=text, text_color=color, font=FONT_SMALL, width=width, anchor="w").pack(
                    side="left", padx=(10, 0), pady=6)

        pos = portfolio.position(self.fund["id"], closes)
        if pos is None or pos["value"] is None:
            self.summary.configure(text="")
            return
        pct = f" ({_signed(pos['gain_pct'], _fmt_es(pos['gain_pct'], 2))} %)" if pos["gain_pct"] is not None else ""
        self.summary.configure(
            text=f"Invertido: {_money(pos['invested'], self.currency)}   ·   "
                 f"Valor actual: {_money(pos['value'], self.currency)}   ·   "
                 f"Ganancia: {_signed(pos['gain'], _money(pos['gain'], self.currency))}{pct}",
            text_color=c["up"] if pos["gain"] > 0 else (c["down"] if pos["gain"] < 0 else c["text_primary"]),
        )


class UsersDialog(ctk.CTkToplevel):
    """Añadir, renombrar, borrar y seleccionar usuarios. Al seleccionar uno se cierra
    y la ventana principal pasa a mostrar sus fondos, aportaciones y colores."""

    def __init__(self, master, app):
        super().__init__(master)
        self.title("Usuarios")
        _apply_icon(self)
        self.app = app
        self.colors = c = app.colors
        self._busy = False
        self.configure(fg_color=c["bg_app"])
        self.transient(master)
        self.grab_set()
        self._icon = ctk.CTkImage(light_image=_user_icon(c["text_primary"]),
                                  dark_image=_user_icon(c["text_primary"]), size=(18, 18))

        ctk.CTkLabel(self, text="Usuarios", font=FONT_TITLE, text_color=c["text_primary"]).pack(
            anchor="w", padx=20, pady=(20, 0))
        ctk.CTkLabel(self, text="Cada usuario tiene sus propios fondos, aportaciones y colores.",
                     font=FONT_SMALL, text_color=c["text_muted"]).pack(anchor="w", padx=20)

        form = ctk.CTkFrame(self, fg_color=c["bg_card"], corner_radius=12, border_width=BORDER_W, border_color=c["border"])
        form.pack(fill="x", padx=20, pady=(14, 0))
        row = ctk.CTkFrame(form, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=14)
        self.name_entry = ctk.CTkEntry(row, placeholder_text="Nombre del nuevo usuario", height=38,
                                       border_width=BORDER_W, border_color=c["border"], font=FONT_BODY)
        self.name_entry.pack(side="left", fill="x", expand=True)
        self.name_entry.bind("<Return>", lambda _e: self._add())
        ctk.CTkButton(row, text="+  Añadir", width=110, height=38, corner_radius=10,
                      fg_color=c["accent"], hover_color=c["accent_hover"], font=("Segoe UI Semibold", 13),
                      command=self._add).pack(side="left", padx=(10, 0))

        ctk.CTkLabel(self, text="Pulsa un usuario para seleccionarlo", font=FONT_SMALL,
                     text_color=c["text_muted"]).pack(anchor="w", padx=20, pady=(14, 4))
        self.list_frame = ctk.CTkScrollableFrame(self, fg_color=c["bg_card"], height=230, corner_radius=12,
                                                 border_width=BORDER_W, border_color=c["border"])
        self.list_frame.pack(fill="both", expand=True, padx=20)

        ctk.CTkButton(
            self, text="Cerrar", height=38, corner_radius=10, fg_color="transparent",
            border_width=BORDER_W, border_color=c["border"], text_color=c["text_muted"], hover_color=c["bg_card_hover"],
            command=self.destroy,
        ).pack(fill="x", padx=20, pady=16)

        self._render()
        self.update_idletasks()
        scaling = ctk.ScalingTracker.get_window_scaling(master)
        _position_over_parent(self, master, max(460, round(self.winfo_reqwidth() / scaling)),
                              round(self.winfo_reqheight() / scaling))
        self.after(50, self.name_entry.focus_set)

    def _render(self):
        c = self.colors
        for w in self.list_frame.winfo_children():
            w.destroy()
        cur = users.current()
        all_users = users.list_users()
        for u in all_users:
            active = cur is not None and u["id"] == cur["id"]
            line = ctk.CTkFrame(
                self.list_frame, fg_color=c["bg_card_selected"] if active else c["bg_card_hover"], corner_radius=10,
                height=50, border_width=BORDER_W_SELECTED if active else BORDER_W,
                border_color=c["accent"] if active else c["border"])
            line.pack(fill="x", pady=4, padx=2)
            line.pack_propagate(False)
            # Botones a la derecha primero (pack reparte el espacio por orden). La ✕
            # está siempre, también con un solo usuario (ver users.delete_user).
            delete_btn = ctk.CTkButton(line, text="✕", width=34, height=30, corner_radius=8, fg_color="transparent",
                                       hover_color=c["bg_card"], text_color=c["text_muted"], font=FONT_BODY,
                                       command=lambda usr=u: self._delete(usr))
            delete_btn.pack(side="right", padx=(0, 8))
            Tooltip(delete_btn, "Borrar este usuario (pide confirmación)", c)
            rename_btn = ctk.CTkButton(line, text="✎", width=34, height=30, corner_radius=8, fg_color="transparent",
                                       hover_color=c["bg_card"], text_color=c["text_muted"], font=FONT_BODY,
                                       command=lambda usr=u: self._rename(usr))
            rename_btn.pack(side="right", padx=(0, 2))
            Tooltip(rename_btn, "Cambiar el nombre de este usuario", c)
            icon = ctk.CTkLabel(line, text="", image=self._icon, width=22)
            icon.pack(side="left", padx=(14, 8))
            name = ctk.CTkLabel(line, text=u["name"], anchor="w", text_color=c["text_primary"],
                                font=("Segoe UI Semibold", 13) if active else FONT_BODY, cursor="hand2")
            name.pack(side="left")
            widgets = [line, icon, name]
            if active:
                tag = ctk.CTkLabel(line, text="  ✓ activo", text_color=c["accent"], font=FONT_SMALL)
                tag.pack(side="left")
                widgets.append(tag)
            for w in widgets:
                w.bind("<ButtonRelease-1>", lambda _e, uid=u["id"]: self._select(uid))

    def _add(self):
        try:
            user = users.add_user(self.name_entry.get())
        except ValueError as exc:
            messagebox.showerror("Usuario no válido", str(exc), parent=self)
            return
        self.name_entry.delete(0, "end")
        self._render()
        applog.info("Usuario creado desde la ventana: %s", user)

    def _select(self, user_id):
        # Aplazado: se destruye esta ventana (con la fila pulsada dentro) y quizá se
        # reconstruye la principal; nunca dentro del propio evento de clic.
        if self._busy:
            return
        self._busy = True
        self.after(30, lambda: self._do_select(user_id))

    def _do_select(self, user_id):
        app = self.app
        self.destroy()
        try:
            app._switch_user(user_id)
        except Exception:
            applog.log_exception("Fallo al cambiar al usuario %s", user_id)

    def _delete(self, user):
        n_funds = self._count_funds(user["id"])
        extra = f" y sus {n_funds} fondo(s) con sus aportaciones" if n_funds else ""
        message = f"¿Seguro que quieres borrar el usuario «{user['name']}»{extra}?"
        if len(users.list_users()) == 1:
            message += (f"\n\nEs el único usuario: el programa quedará vacío, con un usuario "
                        f"nuevo llamado «{users.DEFAULT_NAME}» y los mismos colores.")
        if not _confirm_delete("Borrar usuario", message + "\n\nNo se puede deshacer.",
                               parent=self, colors=self.colors):
            return
        cur = users.current()
        was_active = cur is not None and cur["id"] == user["id"]
        try:
            users.delete_user(user["id"])
        except ValueError as exc:
            messagebox.showerror("No se puede borrar", str(exc), parent=self)
            return
        # La fila con el ✕ pulsado se destruye al repintar: aplazado.
        self.after(30, lambda: self._after_delete(was_active))

    def _after_delete(self, was_active):
        if was_active:
            self.app._on_active_user_changed()
        if self.winfo_exists():
            self._render()

    @staticmethod
    def _count_funds(user_id):
        path = os.path.join(users.user_dir(user_id), "funds.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return len(json.load(f))
        except (OSError, ValueError):
            return 0

    def _rename(self, user):
        RenameUserDialog(self, self.colors, user, on_done=self._after_rename)

    def _after_rename(self):
        self._render()
        self.app._refresh_user_button()


class RenameUserDialog(ctk.CTkToplevel):
    def __init__(self, master, colors, user, on_done):
        super().__init__(master)
        self.title("Renombrar usuario")
        _apply_icon(self)
        self._master = master
        self.user = user
        self.on_done = on_done
        c = colors
        self.configure(fg_color=c["bg_app"])
        self.transient(master)
        self.grab_set()
        ctk.CTkLabel(self, text="Nuevo nombre", font=FONT_SMALL, text_color=c["text_muted"]).pack(
            anchor="w", padx=20, pady=(18, 4))
        self.entry = ctk.CTkEntry(self, width=300, height=38, border_width=BORDER_W, border_color=c["border"],
                                  font=FONT_BODY)
        self.entry.insert(0, user["name"])
        self.entry.pack(fill="x", padx=20)
        self.entry.bind("<Return>", lambda _e: self._save())
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=20, pady=16)
        ctk.CTkButton(buttons, text="Guardar", width=120, height=36, corner_radius=10,
                      fg_color=c["accent"], hover_color=c["accent_hover"], command=self._save).pack(side="right")
        ctk.CTkButton(buttons, text="Cancelar", width=120, height=36, corner_radius=10, fg_color="transparent",
                      border_width=BORDER_W, border_color=c["border"], text_color=c["text_muted"],
                      hover_color=c["bg_card_hover"], command=self._close).pack(side="right", padx=(0, 8))
        self.update_idletasks()
        scaling = ctk.ScalingTracker.get_window_scaling(master)
        _position_over_parent(self, master, round(self.winfo_reqwidth() / scaling),
                              round(self.winfo_reqheight() / scaling))
        self.after(50, lambda: (self.entry.focus_set(), self.entry.select_range(0, "end")))

    def _save(self):
        try:
            users.rename_user(self.user["id"], self.entry.get())
        except ValueError as exc:
            messagebox.showerror("Nombre no válido", str(exc), parent=self)
            return
        self._close()
        self.on_done()

    def _close(self):
        master = self._master
        self.destroy()
        # Tk no devuelve el grab a la ventana anterior al cerrar esta: se recupera a mano.
        try:
            master.grab_set()
        except Exception:
            pass


class FundRow(ctk.CTkFrame):
    def __init__(self, master, colors, fund, on_click, selected=False):
        super().__init__(
            master, fg_color=colors["bg_card_selected"] if selected else colors["bg_card"],
            corner_radius=10, height=48,
            border_width=BORDER_W_SELECTED if selected else BORDER_W, border_color=colors["accent"] if selected else colors["border"],
        )
        self.fund = fund
        self.colors = colors
        self.on_click = on_click
        self.pack_propagate(False)

        dot = ctk.CTkLabel(self, text="●", text_color=fund["color"], font=("Segoe UI", 16), width=20)
        dot.pack(side="left", padx=(12, 0))
        label = ctk.CTkLabel(self, text=fund["name"], text_color=colors["text_primary"], font=FONT_BODY, anchor="w")
        label.pack(side="left", fill="x", expand=True, padx=(4, 12))

        for widget in (self, dot, label):
            widget.bind("<ButtonRelease-1>", lambda _e: self.on_click(fund["id"]))

    def set_selected(self, selected):
        c = self.colors
        self.configure(
            fg_color=c["bg_card_selected"] if selected else c["bg_card"],
            border_color=c["accent"] if selected else c["border"],
            border_width=BORDER_W_SELECTED if selected else BORDER_W,
        )


class MisFondosApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MisFondos — Seguimiento de fondos indexados")
        _apply_icon(self.root)
        # Ancho inicial y mínimo pensados para que la barra de vistas y el recuadro
        # de subidas/bajadas quepan con HEADER_GAP entre ellos (si la ventana es más
        # estrecha se tocan); nunca más anchos que la pantalla (en px lógicos). El ancho
        # se pide a Windows: winfo_screenwidth() de Tk lo da ya dividido por el
        # escalado del sistema (1536 en una pantalla de 1920 al 125 %).
        screen_w = ctypes.windll.user32.GetSystemMetrics(0) / ctk.ScalingTracker.get_window_scaling(self.root)
        self.root.geometry(f"{int(min(WINDOW_W, screen_w - 40))}x680")
        self.root.minsize(int(min(WINDOW_MIN_W, screen_w - 40)), 560)

        users.init()  # apunta config a la carpeta del usuario activo (y migra datos antiguos)
        self.theme_name = settings.get_theme()
        self.colors = config.THEMES[self.theme_name]

        self.view_mode = tk.StringVar(value="individual")
        self.period = tk.StringVar(value="6M")
        self.normalize_var = tk.BooleanVar(value=True)
        self.multi_count = MULTI_COUNTS[0]  # cuántas gráficas en la vista "multi"
        self._multi_panels = []
        self._multi_info = (0, 0)  # (gráficas dibujadas, fondos en la lista)
        self.selected_fund_id = None
        self.fund_rows = {}
        self._ui_queue = queue.Queue()
        self._rebuilding = False
        self._table_sort = (None, True)  # (columna, descendente); None = orden de la lista
        self._last_refresh = None

        # Icono junto al reloj: se crea antes del primer dibujado para que este ya
        # le ponga el resumen de la cartera. Si falla, el programa sigue igual que
        # antes (la X cierra del todo).
        self.tray = tray.TrayIcon(self._ui_queue)
        self.tray.start()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Se destruya como se destruya la ventana, el icono se quita con ella (si no,
        # queda un icono fantasma junto al reloj hasta que se pasa el ratón por encima).
        self.root.bind("<Destroy>", lambda e: self.tray.stop() if e.widget is self.root else None, add="+")
        system.take_show_request()  # descarta un aviso viejo de una sesión anterior

        ctk.set_appearance_mode(self.colors["appearance"])
        self.root.configure(fg_color=self.colors["bg_app"])
        self._build_layout()
        self.reload_funds()
        self._start_scheduler()
        self.root.after(200, self._poll_ui_queue)

    # ---------- ventana e icono junto al reloj ----------
    def _on_close(self):
        """La X: si está activado (por defecto), la ventana se esconde y MisFondos
        sigue funcionando junto al reloj, actualizando los fondos."""
        if self.tray.running and settings.get_close_to_tray():
            self.root.withdraw()
            if not settings.tray_notice_shown():
                self.tray.notify(
                    "MisFondos sigue funcionando aquí, junto al reloj, y actualiza tus fondos solo. "
                    "Clic en el icono para abrirlo; clic derecho → Salir para cerrarlo del todo.")
                settings.mark_tray_notice_shown()
            applog.info("Ventana escondida junto al reloj")
        else:
            self._quit()

    def _show_window(self):
        self.root.deiconify()
        if self.root.state() == "iconic":
            self.root.state("normal")
        # Windows no deja que un programa se ponga delante por su cuenta; subirla a
        # "siempre encima" un instante sí la trae al frente, sin dejarla así.
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(300, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

    def _quit(self):
        applog.info("Cerrando MisFondos")
        self.tray.stop()
        self.root.destroy()

    def _update_tray_title(self):
        if not self.tray.running:
            return
        try:
            user = users.current()
            lines = [f"MisFondos · {user['name']}" if user else "MisFondos"]
            t = _portfolio_totals(store.list_funds())
            if t is None:
                lines.append("Cartera: sin aportaciones apuntadas")
            else:
                line = f"Cartera: {_money(t['value'], t['currency'])}"
                if t["pct"] is not None:
                    line += f" ({_signed(t['pct'], _fmt_es(t['pct'], 2))} %)"
                lines.append(line)
            if self._last_refresh:
                lines.append(f"Actualizado: {self._last_refresh:%d/%m %H:%M}")
            self.tray.set_title("\n".join(lines))
        except Exception:
            applog.log_exception("No se pudo calcular el resumen del icono junto al reloj")

    # ---------- usuarios ----------
    def _open_users_dialog(self):
        UsersDialog(self.root, self)

    def _user_button_text(self):
        user = users.current()
        name = user["name"] if user else "Usuario"
        # hueco del texto = ancho del botón − icono − márgenes internos
        return _fit_text(self.root, name, USER_BTN_FONT, USER_BTN_TEXT_W)

    def _refresh_user_button(self):
        self.user_button.configure(text=self._user_button_text())

    def _switch_user(self, user_id):
        cur = users.current()
        if cur and cur["id"] == user_id:
            return
        users.activate(user_id)
        self._on_active_user_changed()

    def _on_active_user_changed(self):
        """Carga en pantalla los fondos, aportaciones y tema del usuario activo."""
        self.selected_fund_id = None
        new_theme = settings.get_theme()
        if new_theme != self.theme_name:
            self._apply_theme(new_theme)  # reconstruye la interfaz (incluido el botón)
        else:
            self._refresh_user_button()
            self.reload_funds()
        self._manual_refresh()  # sus fondos pueden tener el histórico sin actualizar

    # ---------- tema ----------
    def _open_settings_dialog(self):
        SettingsDialog(self.root, self)

    def _apply_theme(self, theme_key):
        if theme_key == self.theme_name:
            return
        applog.info("Cambiando de tema: %s -> %s", self.theme_name, theme_key)
        # Bandera de reentrada: mientras se reconstruye la interfaz no se procesan
        # redibujados en cola (del hilo de refresco) ni eventos de ratón sobre la
        # gráfica, para no tocar un canvas/figure a medio destruir (eso colgaba la app).
        self._rebuilding = True
        try:
            old_appearance = self.colors["appearance"]
            new_colors = config.THEMES[theme_key]
            settings.set_theme(theme_key)
            self.theme_name = theme_key
            self.colors = new_colors
            # ctk.set_appearance_mode() notifica a cada ventana viva (root, diálogos
            # abiertos) para que actualice su color de barra de título vía la API de
            # Windows (DWM); si no hace falta cambiar entre claro/oscuro no se llama en
            # absoluto, para no disparar esa ruta nativa en cada clic sobre un tema.
            if new_colors["appearance"] != old_appearance:
                ctk.set_appearance_mode(new_colors["appearance"])
                self.root.update_idletasks()
            self.root.configure(fg_color=self.colors["bg_app"])
            # Solo se destruyen los frames de la propia ventana principal: si hay un
            # diálogo (p.ej. Configuración) abierto encima, no se toca.
            for w in self._layout_frames:
                w.destroy()
            self._build_layout()
            # La interfaz nueva ya existe: se levanta la protección ANTES de dibujar.
            # Si se levantaba en el finally, el _redraw de reload_funds() se saltaba y
            # la gráfica (y el indicador) quedaban vacíos tras cada cambio de tema.
            self._rebuilding = False
            self.reload_funds()
        except Exception:
            applog.log_exception("Fallo al aplicar el tema %s", theme_key)
            raise
        finally:
            self._rebuilding = False

    # ---------- layout ----------
    def _build_layout(self):
        c = self.colors
        sidebar = ctk.CTkFrame(self.root, fg_color=c["bg_sidebar"], width=SIDEBAR_W, corner_radius=0)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        header = ctk.CTkFrame(sidebar, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(22, 10))
        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(fill="x")
        try:
            logo = Image.open(config.LOGO_FILE)
            self._logo_img = ctk.CTkImage(light_image=logo, dark_image=logo, size=(30, 30))
            ctk.CTkLabel(title_row, text="", image=self._logo_img, width=30).pack(side="left", padx=(0, 8))
        except Exception:
            applog.log_exception("No se pudo cargar el logo desde %s", config.LOGO_FILE)
        ctk.CTkLabel(title_row, text="Mis fondos", font=("Segoe UI Semibold", 18), text_color=c["text_primary"]).pack(
            side="left", anchor="w"
        )
        gear = ctk.CTkButton(
            title_row, text="⚙", width=32, height=32, corner_radius=TITLE_BTN_RADIUS,
            fg_color="transparent", hover_color=c["bg_card_hover"], text_color=c["text_muted"],
            border_width=BORDER_W, border_color=c["border"],
            font=("Segoe UI", 15), command=self._open_settings_dialog,
        )
        gear.pack(side="right")
        Tooltip(gear, "Configuración: colores, arrancar con Windows y reloj", c)
        # Botón de usuario: entre el título y la rueda. Ancho fijo (con autoajuste
        # CustomTkinter deja una muesca) y nombre recortado con "…" si no cabe.
        self.user_button = ctk.CTkButton(
            title_row, text=self._user_button_text(),
            width=USER_BTN_W, height=32, corner_radius=TITLE_BTN_RADIUS, anchor="center",
            fg_color="transparent", hover_color=c["bg_card_hover"], text_color=c["text_primary"],
            border_width=BORDER_W, border_color=c["border"], font=USER_BTN_FONT,
            command=self._open_users_dialog,
        )
        self.user_button.pack(side="right", padx=(0, 6))
        Tooltip(self.user_button, "Usuario activo: pulsa para cambiar, añadir o borrar usuarios", c)
        ctk.CTkLabel(header, text="Seguimiento de fondos indexados", font=FONT_SMALL, text_color=c["text_muted"]).pack(
            anchor="w"
        )

        self.fund_list_frame = ctk.CTkScrollableFrame(sidebar, fg_color="transparent")
        self.fund_list_frame.pack(fill="both", expand=True, padx=14, pady=6)

        btn_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        btn_frame.pack(fill="x", padx=14, pady=(4, 6))
        ctk.CTkButton(
            btn_frame, text="+  Añadir fondo", height=40, corner_radius=10, fg_color=c["accent"],
            hover_color=c["accent_hover"], font=("Segoe UI Semibold", 13), command=self._open_add_dialog,
        ).pack(fill="x", pady=3)
        ctk.CTkButton(
            btn_frame, text="Eliminar seleccionado", height=34, corner_radius=10,
            fg_color="transparent", border_width=BORDER_W, border_color=c["border"], hover_color=c["bg_card_hover"],
            text_color=c["text_muted"], font=FONT_SMALL, command=self._remove_selected,
        ).pack(fill="x", pady=3)
        ctk.CTkButton(
            btn_frame, text="↻  Actualizar ahora", height=34, corner_radius=10,
            fg_color="transparent", border_width=BORDER_W, border_color=c["border"], hover_color=c["bg_card_hover"],
            text_color=c["text_muted"], font=FONT_SMALL, command=self._manual_refresh,
        ).pack(fill="x", pady=3)

        self.status_label = ctk.CTkLabel(
            sidebar, text="", font=FONT_SMALL, text_color=c["text_muted"], wraplength=250, justify="left", anchor="w"
        )
        self.status_label.pack(fill="x", padx=18, pady=(6, 16))

        divider = ctk.CTkFrame(self.root, fg_color=c["border"], width=BORDER_W, corner_radius=0)
        divider.pack(side="left", fill="y")

        main = ctk.CTkFrame(self.root, fg_color=c["bg_app"], corner_radius=0)
        main.pack(side="left", fill="both", expand=True)

        self._layout_frames = [sidebar, divider, main]

        header = ctk.CTkFrame(main, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(22, 0))
        controls = ctk.CTkFrame(header, fg_color="transparent")
        controls.pack(side="left", anchor="n")

        self.view_switch = PillSwitch(
            controls, c, list(VIEW_LABELS.values()), command=self._on_view_switch,
            height=44, font=FONT_BODY, radius=12,
        )
        self.view_switch.set(VIEW_LABELS.get(self.view_mode.get()))  # en "multi", ninguna marcada
        self.view_switch.pack(anchor="w")

        # Fila de abajo: periodos y, a continuación, las vistas de varias gráficas.
        period_row = ctk.CTkFrame(controls, fg_color="transparent")
        period_row.pack(anchor="w", pady=(12, 0))
        # "YTD" (year to date) se muestra como el año en curso, igual que MyInvestor.
        # Internamente la clave sigue siendo "YTD"; el mapa se fija al construir la
        # interfaz para que no se descuadre si la app sigue abierta al cambiar de año.
        self._period_by_label = {(str(dt.date.today().year) if k == "YTD" else k): k for k in PERIODS}
        self.period_switch = PillSwitch(
            period_row, c, list(self._period_by_label), command=self._on_period_switch,
            height=38, font=FONT_SMALL, radius=10,
        )
        self.period_switch.set(next(lbl for lbl, k in self._period_by_label.items() if k == self.period.get()))
        self.period_switch.pack(side="left")

        self.multi_group = ctk.CTkFrame(period_row, fg_color="transparent")
        self.multi_group.pack(side="left", padx=(18, 0))
        multi_caption = ctk.CTkLabel(self.multi_group, text="Ver juntas", font=FONT_SMALL, text_color=c["text_muted"])
        multi_caption.pack(side="left", padx=(0, 8))
        self.multi_switch = PillSwitch(
            self.multi_group, c, [str(n) for n in MULTI_COUNTS], command=self._on_multi_switch,
            height=38, font=FONT_SMALL, radius=10,
        )
        self.multi_switch.set(str(self.multi_count) if self.view_mode.get() == "multi" else None)
        self.multi_switch.pack(side="left")
        multi_help = ("Ver a la vez las 3, 4, 5 o 6 primeras gráficas de tu lista de fondos.\n"
                      "Si son impares, la más grande es la que más rentabilidad da en el periodo elegido.")
        Tooltip(multi_caption, multi_help, c)
        Tooltip(self.multi_switch, multi_help, c)

        # Lado derecho de la cabecera: en vista individual, el indicador de subida/bajada
        # del último valor liquidativo; en vista global, la casilla de normalizar (que
        # solo afecta a esa vista). Ambos se crean una vez y se muestran/ocultan con
        # pack/pack_forget: nunca se destruyen desde un redibujado, porque la casilla
        # dispara _redraw desde su propio clic (ver el cuelgue de los temas).
        self.normalize_check = ctk.CTkCheckBox(
            header, text="Normalizar (base 100)", variable=self.normalize_var, command=self._redraw,
            font=FONT_SMALL, text_color=c["text_muted"], fg_color=c["accent"], hover_color=c["accent_hover"],
            checkbox_width=18, checkbox_height=18,
        )
        Tooltip(self.normalize_check,
                "Pone todos los fondos en 100 al principio del periodo, para comparar\n"
                "cuánto ha subido o bajado cada uno aunque sus precios sean muy distintos.\n"
                "Ejemplo: 112 = ha ganado un 12 %  ·  95 = ha perdido un 5 %.\n"
                "Sin marcar se ve el precio real (valor liquidativo) de cada fondo.", c)
        # En la vista de varias gráficas: qué se está viendo y por qué una es más grande.
        self.multi_note = ctk.CTkLabel(header, text="", font=FONT_SMALL, text_color=c["text_muted"],
                                       justify="right", anchor="e", wraplength=260)
        self._build_change_indicator(header)
        self._build_portfolio_strip(main)

        chart_card = ctk.CTkFrame(main, fg_color=c["bg_card"], corner_radius=16, border_width=BORDER_W, border_color=c["border"])
        chart_card.pack(fill="both", expand=True, padx=24, pady=(14, 20))
        self.chart_card = chart_card
        self._build_returns_table(main)

        self.fig = Figure(figsize=(7, 5), dpi=100, facecolor=c["bg_card"])
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_card)
        # width/height pequeños = tamaño *mínimo pedido*; pack(fill/expand) lo agranda.
        # Sin esto el lienzo pide el tamaño de la figura (700x500 px, más con el
        # escalado de DPI) y en ventanas estrechas empuja la gráfica y el indicador
        # de subida/bajada fuera del borde derecho.
        self.canvas.get_tk_widget().configure(bg=c["bg_card"], highlightthickness=0, width=320, height=200)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=18, pady=18)
        self._plot_series = []
        self._hover_ann = None
        self._hover_dot = None
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)
        self.canvas.mpl_connect("figure_leave_event", self._on_leave_chart)
        self.canvas.mpl_connect("resize_event", self._on_chart_resize)

    # ---------- franja "mi cartera" ----------
    def _build_portfolio_strip(self, parent):
        """Resumen de dinero invertido. Como el indicador, se crea una vez y solo se
        actualiza con configure(): nunca se destruye desde un redibujado."""
        c = self.colors
        card = ctk.CTkFrame(parent, fg_color=c["bg_card"], corner_radius=12, border_width=BORDER_W, border_color=c["border"])
        card.pack(fill="x", padx=24, pady=(14, 0))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(10, 0))

        self.pf_values = {}
        for key, caption in (("invested", "Invertido"), ("value", "Valor actual"),
                             ("gain", "Ganancia / pérdida"), ("pct", "Rentabilidad")):
            block = ctk.CTkFrame(row, fg_color="transparent")
            block.pack(side="left", padx=(0, 32))
            ctk.CTkLabel(block, text=caption, font=FONT_SMALL, text_color=c["text_muted"], anchor="w").pack(anchor="w")
            lbl = ctk.CTkLabel(block, text="—", font=("Segoe UI Semibold", 16), text_color=c["text_primary"], anchor="w")
            lbl.pack(anchor="w")
            self.pf_values[key] = lbl

        self.pf_button = ctk.CTkButton(
            row, text="Mis aportaciones", height=34, corner_radius=10,
            fg_color=c["accent"], hover_color=c["accent_hover"], font=FONT_SMALL,
            command=self._open_portfolio_dialog,
        )
        self.pf_button.pack(side="right")

        self.pf_hint = ctk.CTkLabel(card, text="", font=FONT_SMALL, text_color=c["text_muted"], anchor="w", justify="left")
        self.pf_hint.pack(fill="x", padx=16, pady=(2, 10))

    def _open_portfolio_dialog(self):
        fund = next((f for f in store.list_funds() if f["id"] == self.selected_fund_id), None)
        if fund:
            PortfolioDialog(self.root, self, fund)

    def _set_pf_values(self, invested, value, gain, pct, currency):
        c = self.colors
        dash = "—"
        self.pf_values["invested"].configure(text=_money(invested, currency) if invested is not None else dash)
        self.pf_values["value"].configure(text=_money(value, currency) if value is not None else dash)
        color = c["text_primary"] if gain in (None, 0) else (c["up"] if gain > 0 else c["down"])
        self.pf_values["gain"].configure(
            text=_signed(gain, _money(gain, currency)) if gain is not None else dash, text_color=color)
        self.pf_values["pct"].configure(
            text=_signed(pct, f"{_fmt_es(pct, 2)} %") if pct is not None else dash,
            text_color=color if pct is not None else c["text_primary"])

    def _update_portfolio_strip(self):
        funds = store.list_funds()
        if self.view_mode.get() == "individual":
            if not self.pf_button.winfo_manager():
                self.pf_button.pack(side="right")
            fund = next((f for f in funds if f["id"] == self.selected_fund_id), None)
            if not fund:
                self.pf_button.pack_forget()
                self._set_pf_values(None, None, None, None, "")
                self.pf_hint.configure(text="Añade un fondo para empezar.")
                return
            closes = data_fetcher.load_history(fund["id"])["Close"].dropna()
            pos = portfolio.position(fund["id"], closes)
            cur = fund.get("currency", "")
            if pos is None:
                self._set_pf_values(None, None, None, None, cur)
                self.pf_hint.configure(
                    text="Apunta tus aportaciones en este fondo (botón «Mis aportaciones») para ver "
                         "cuánto dinero tienes y cuánto has ganado.")
                return
            self._set_pf_values(pos["invested"], pos["value"], pos["gain"], pos["gain_pct"], cur)
            hint = (f"{_fmt_es(pos['units'], 4)} participaciones · {pos['movements']} movimiento(s)")
            if pos["last_nav"] is not None:
                hint += f" · valorado al VL del {pos['last_date']:%d/%m/%Y}"
            if pos["missing_nav"]:
                hint += (f"  ⚠ {pos['missing_nav']} movimiento(s) sin valor liquidativo en su fecha: "
                         "indica sus participaciones a mano")
            self.pf_hint.configure(text=hint)
            return

        # Vista global: suma de toda la cartera
        self.pf_button.pack_forget()
        t = _portfolio_totals(funds)
        if t is None:
            self._set_pf_values(None, None, None, None, "")
            self.pf_hint.configure(text="Cartera completa: aún no has apuntado aportaciones en ningún fondo.")
            return
        self._set_pf_values(t["invested"], t["value"], t["gain"], t["pct"], t["currency"])
        hint = f"Cartera completa: {t['funds']} fondo(s) con aportaciones"
        if len(t["currencies"]) > 1:
            hint += f"  ⚠ mezcla divisas ({', '.join(sorted(t['currencies']))}) sin convertir"
        self.pf_hint.configure(text=hint)

    # ---------- tabla de rentabilidades ----------
    def _build_returns_table(self, parent):
        c = self.colors
        card = ctk.CTkFrame(parent, fg_color=c["bg_card"], corner_radius=16, border_width=BORDER_W, border_color=c["border"])
        self.table_card = card  # se empaqueta/oculta en _update_header según la vista
        ctk.CTkLabel(card, text="Rentabilidades", font=("Segoe UI Semibold", 15), text_color=c["text_primary"]).pack(
            anchor="w", padx=24, pady=(18, 6))

        # Cabecera dentro del mismo marco desplazable que las filas: así comparten
        # ancho (la barra de desplazamiento no descuadra las columnas).
        scroll = ctk.CTkScrollableFrame(card, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=14)
        # Cabeceras como CTkLabel (mismo widget y anclaje que los números: alinean al
        # píxel; un CTkButton mete relleno interno y descuadraba unos px). Se ordena
        # al soltar el clic; solo se reconstruyen las filas, nunca la cabecera.
        header = ctk.CTkFrame(scroll, fg_color="transparent")
        header.pack(fill="x", pady=(0, 4))
        self._table_headers = {}
        year = str(dt.date.today().year)
        for i, (key, title, width) in enumerate(reversed(RETURN_COLUMNS)):
            title = year if key == "YTD" else title
            lbl = ctk.CTkLabel(header, text=title, width=width, anchor="e", text_color=c["text_muted"],
                               font=FONT_SMALL, cursor="hand2")
            lbl.pack(side="right", padx=(4, 12 if i == 0 else 0), pady=4)
            lbl.bind("<ButtonRelease-1>", lambda _e, k=key: self._sort_table(k))
            self._table_headers[key] = (lbl, title)
        name_lbl = ctk.CTkLabel(header, text="Fondo", anchor="w", text_color=c["text_muted"], font=FONT_SMALL,
                                cursor="hand2")
        name_lbl.pack(side="left", padx=(12, 0), pady=4)
        name_lbl.bind("<ButtonRelease-1>", lambda _e: self._sort_table("name"))
        self._table_headers["name"] = (name_lbl, "Fondo")
        self._table_rows = ctk.CTkFrame(scroll, fg_color="transparent")
        self._table_rows.pack(fill="x")

        note = ctk.CTkLabel(
            card, font=FONT_SMALL, text_color=c["text_muted"], justify="left", anchor="w",
            text="Rentabilidad del valor liquidativo en cada periodo. «3A anual.» es la media por año de los "
                 "últimos 3 años y «Mi rentabilidad», la de tus aportaciones apuntadas. Pulsa una cabecera "
                 "para ordenar y el nombre de un fondo para ver su gráfica. En negrita, el mejor de cada columna.",
        )
        note.pack(fill="x", padx=24, pady=(8, 16))
        # El texto se ajusta al ancho de la tarjeta (no al de la propia etiqueta, que
        # cambiaría al reajustar y podría realimentarse). wraplength va en px lógicos.
        card.bind("<Configure>", lambda e: note.configure(
            wraplength=max(200, e.width / ctk.ScalingTracker.get_widget_scaling(card) - 60)))

    def _sort_table(self, key):
        current, desc = self._table_sort
        # Primer clic en una columna numérica: de mejor a peor; en "Fondo": A→Z.
        desc = (not desc) if key == current else (key != "name")
        self._table_sort = (key, desc)
        self._render_returns_table(store.list_funds())

    def _open_fund_from_table(self, fund_id):
        self.selected_fund_id = fund_id
        for fid, row in self.fund_rows.items():
            row.set_selected(fid == fund_id)
        self.view_switch.set(VIEW_LABELS["individual"])
        self._on_view_switch(VIEW_LABELS["individual"])

    def _render_returns_table(self, funds):
        c = self.colors
        for w in self._table_rows.winfo_children():
            w.destroy()
        rows = []
        for f in funds:
            closes = data_fetcher.load_history(f["id"])["Close"].dropna()
            pos = portfolio.position(f["id"], closes)
            rows.append({
                "fund": f,
                "nav": float(closes.iloc[-1]) if len(closes) else None,
                "nav_date": closes.index[-1] if len(closes) else None,
                "1M": metrics.period_return(closes, "1M"),
                "3M": metrics.period_return(closes, "3M"),
                "YTD": metrics.period_return(closes, "YTD"),
                "1A": metrics.period_return(closes, "1A"),
                "3A": metrics.period_return(closes, "3A", annualize=True),
                "mine": pos["gain_pct"] if pos else None,
            })
        if not rows:
            ctk.CTkLabel(self._table_rows, text="Añade fondos para ver sus rentabilidades.",
                         font=FONT_BODY, text_color=c["text_muted"]).pack(anchor="w", padx=10, pady=12)
            return

        key, desc = self._table_sort
        if key == "name":
            rows.sort(key=lambda r: _sort_text(r["fund"]["name"]), reverse=desc)
        elif key:  # los que no tienen dato (histórico corto, sin aportaciones) siempre al final
            with_value = sorted((r for r in rows if r[key] is not None), key=lambda r: r[key], reverse=desc)
            rows = with_value + [r for r in rows if r[key] is None]
        for k, (btn, title) in self._table_headers.items():
            arrow = (" ▼" if desc else " ▲") if k == key else ""
            btn.configure(text=title + arrow, text_color=c["text_primary"] if k == key else c["text_muted"])

        best = {}
        for k in ("1M", "3M", "YTD", "1A", "3A", "mine"):
            values = [r[k] for r in rows if r[k] is not None]
            if len(values) >= 2:
                best[k] = max(values)

        for i, r in enumerate(rows):
            line = ctk.CTkFrame(self._table_rows, fg_color=c["bg_card_hover"] if i % 2 == 0 else "transparent",
                                corner_radius=8)
            line.pack(fill="x", pady=2)
            for j, (key_, _title, width) in enumerate(reversed(RETURN_COLUMNS)):
                v = r[key_]
                bold = False
                if v is None:
                    text, color = "—", c["text_muted"]
                else:
                    text = _signed(v, f"{_fmt_es(v, 2)} %")
                    color = c["up"] if v > 0 else (c["down"] if v < 0 else c["text_primary"])
                    bold = key_ in best and v == best[key_]
                ctk.CTkLabel(line, text=text, width=width, anchor="e", text_color=color,
                             font=("Segoe UI Semibold", 12) if bold else FONT_BODY).pack(
                    side="right", padx=(4, 12 if j == 0 else 0), pady=8)
            fund = r["fund"]
            cell = ctk.CTkFrame(line, fg_color="transparent")
            cell.pack(side="left", fill="x", expand=True, padx=(10, 0), pady=6)
            dot = ctk.CTkLabel(cell, text="●", text_color=fund["color"], font=("Segoe UI", 14), width=18)
            dot.pack(side="left", anchor="n", pady=(2, 0))
            texts = ctk.CTkFrame(cell, fg_color="transparent")
            texts.pack(side="left", fill="x", expand=True, padx=(4, 0))
            label = ctk.CTkLabel(texts, text=fund["name"], text_color=c["text_primary"], font=FONT_BODY, anchor="w",
                                 cursor="hand2", height=20)
            label.pack(anchor="w")
            sub = "—"
            if r["nav"] is not None:
                symbol = _CURRENCY_SYMBOLS.get((fund.get("currency") or "").upper(), fund.get("currency", ""))
                sub = f"VL {_fmt_es(r['nav'], _nav_decimals(r['nav']))} {symbol} · {r['nav_date']:%d/%m/%Y}"
            sub_label = ctk.CTkLabel(texts, text=sub, text_color=c["text_muted"], font=FONT_SMALL, anchor="w",
                                     height=16)
            sub_label.pack(anchor="w")

            # Nombre y VL se recortan con "…" al ancho que quede libre para la celda
            # (depende del tamaño de la ventana), en vez de cortarse a mitad de letra.
            def fit(event, full=fund["name"], sub_full=sub, lbl=label, sub_lbl=sub_label, cell=cell):
                avail = event.width / ctk.ScalingTracker.get_widget_scaling(cell) - 30
                lbl.configure(text=_fit_text(cell, full, FONT_BODY, avail))
                sub_lbl.configure(text=_fit_text(cell, sub_full, FONT_SMALL, avail))
            cell.bind("<Configure>", fit)
            # <ButtonRelease-1>: la regla de la app para bind manuales (ver FundRow).
            for w in (dot, label):
                w.bind("<ButtonRelease-1>", lambda _e, fid=fund["id"]: self._open_fund_from_table(fid))

    # ---------- indicador de subida/bajada ----------
    def _build_change_indicator(self, parent):
        c = self.colors
        self._indicator = None
        self._header_mode = None
        card = ctk.CTkFrame(parent, fg_color=c["bg_card"], corner_radius=12, border_width=BORDER_W, border_color=c["border"])
        self.indicator_card = card

        self.ind_caption = ctk.CTkLabel(card, text="", font=FONT_SMALL, text_color=c["text_muted"], anchor="e")
        self.ind_caption.pack(anchor="e", padx=16, pady=(10, 0))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(anchor="e", padx=16)
        self.ind_prev = ctk.CTkLabel(row, text="", font=FONT_BODY, text_color=c["text_muted"])
        self.ind_prev.pack(side="left")
        self.ind_arrow = ctk.CTkLabel(row, text="", font=("Segoe UI Semibold", 20))
        self.ind_arrow.pack(side="left", padx=(12, 4))
        self.ind_delta = ctk.CTkLabel(row, text="", font=("Segoe UI Semibold", 12))
        self.ind_delta.pack(side="left")
        self.ind_curr = ctk.CTkLabel(row, text="", font=("Segoe UI Semibold", 18), text_color=c["text_primary"])
        self.ind_curr.pack(side="left", padx=(16, 0))

        self.ind_period = ctk.CTkLabel(card, text="", font=FONT_SMALL, text_color=c["text_muted"], anchor="e")
        self.ind_period.pack(anchor="e", padx=16, pady=(0, 10))

    def _direction_style(self, delta):
        c = self.colors
        if delta > 0:
            return "▲", c["up"]
        if delta < 0:
            return "▼", c["down"]
        return "=", c["text_muted"]

    def _update_header(self):
        mode = self.view_mode.get()
        if mode != self._header_mode:
            self.indicator_card.pack_forget()
            self.normalize_check.pack_forget()
            self.multi_note.pack_forget()
            if mode == "individual":
                self.indicator_card.pack(side="right", anchor="n", padx=(HEADER_GAP, 0))
            elif mode == "global":
                self.normalize_check.pack(side="right", anchor="n", padx=(HEADER_GAP, 0), pady=(8, 0))
            elif mode == "multi":
                self.multi_note.pack(side="right", anchor="n", padx=(HEADER_GAP, 0), pady=(4, 0))
            # Reparto y rentabilidades son a fecha de hoy: los periodos no aplican (los
            # botones de varias gráficas se quedan, para poder llegar a ellas).
            if mode in SNAPSHOT_VIEWS:
                self.period_switch.pack_forget()
            elif not self.period_switch.winfo_manager():
                self.period_switch.pack(side="left", before=self.multi_group)
            # La tabla sustituye a la gráfica (se ocultan, nunca se destruyen).
            if mode == "rentabilidades":
                self.chart_card.pack_forget()
                self.table_card.pack(fill="both", expand=True, padx=24, pady=(14, 20))
            else:
                self.table_card.pack_forget()
                if not self.chart_card.winfo_manager():
                    self.chart_card.pack(fill="both", expand=True, padx=24, pady=(14, 20))
            self._header_mode = mode
        if mode == "multi":
            self.multi_note.configure(text=self._multi_note_text())
        if mode != "individual":
            return

        c = self.colors
        ind = self._indicator
        if ind is None:
            self.ind_caption.configure(text="Sin datos suficientes todavía")
            for lbl in (self.ind_prev, self.ind_arrow, self.ind_delta, self.ind_curr, self.ind_period):
                lbl.configure(text="")
            return

        dec = _nav_decimals(ind["last"])
        delta = ind["last"] - ind["prev"]
        pct = delta / ind["prev"] * 100 if ind["prev"] else 0.0
        arrow, color = self._direction_style(delta)
        sign = "+" if delta > 0 else ""
        self.ind_caption.configure(
            text=f"Valor liquidativo: {ind['prev_date']:%d/%m} → {ind['last_date']:%d/%m/%Y}"
        )
        self.ind_prev.configure(text=_fmt_es(ind["prev"], dec))
        self.ind_arrow.configure(text=arrow, text_color=color)
        self.ind_delta.configure(text=f"{sign}{_fmt_es(delta, dec)} ({sign}{_fmt_es(pct, 2)} %)", text_color=color)
        self.ind_curr.configure(text=_fmt_es(ind["last"], dec))

        if ind["period_pct"] is None:
            self.ind_period.configure(text="")
        else:
            p_arrow, p_color = self._direction_style(ind["period_pct"])
            p_sign = "+" if ind["period_pct"] > 0 else ""
            self.ind_period.configure(
                text=f"{PERIOD_PHRASES.get(self.period.get(), '')}: {p_arrow} {p_sign}{_fmt_es(ind['period_pct'], 2)} %",
                text_color=p_color,
            )

    def _multi_note_text(self):
        shown, total = self._multi_info
        phrase = PERIOD_PHRASES.get(self.period.get(), "").lower()
        lines = []
        if total < self.multi_count:
            lines.append(f"Solo hay {total} fondo{'s' if total != 1 else ''} en tu lista.")
        if shown >= 3 and shown % 2:
            lines.append(f"La gráfica grande es la de más rentabilidad {phrase}.")
        elif shown >= 2:
            lines.append(f"Junto a cada nombre, su rentabilidad {phrase}.")
        return "\n".join(lines)

    def _on_view_switch(self, value):
        mode = next((k for k, lbl in VIEW_LABELS.items() if lbl == value), "individual")
        self.multi_switch.set(None)
        self.view_mode.set(mode)
        self._redraw()

    def _on_multi_switch(self, value):
        self.multi_count = int(value)
        self.view_switch.set(None)  # es otra vista: ninguna de las de arriba queda marcada
        self.view_mode.set("multi")
        self._redraw()

    def _on_period_switch(self, value):
        self.period.set(self._period_by_label.get(value, value))
        self._redraw()

    # ---------- data / fund list ----------
    def reload_funds(self):
        c = self.colors
        self.funds = store.list_funds()
        for w in self.fund_list_frame.winfo_children():
            w.destroy()
        self.fund_rows = {}

        if not self.funds:
            ctk.CTkLabel(
                self.fund_list_frame, text="Añade tu primer fondo\ncon el botón de abajo",
                text_color=c["text_muted"], font=FONT_SMALL, justify="left",
            ).pack(anchor="w", padx=6, pady=10)
        else:
            if self.selected_fund_id is None or not any(f["id"] == self.selected_fund_id for f in self.funds):
                self.selected_fund_id = self.funds[0]["id"]
            for f in self.funds:
                row = FundRow(self.fund_list_frame, c, f, self._select_fund, selected=(f["id"] == self.selected_fund_id))
                row.pack(fill="x", pady=4)
                self.fund_rows[f["id"]] = row

        self._redraw()

    def _select_fund(self, fund_id):
        self.selected_fund_id = fund_id
        for fid, row in self.fund_rows.items():
            row.set_selected(fid == fund_id)
        self._redraw()

    def _open_add_dialog(self):
        AddFundDialog(self.root, self.colors, on_added=lambda fund: self.reload_funds())

    def _remove_selected(self):
        if not self.selected_fund_id:
            return
        fund = next((f for f in self.funds if f["id"] == self.selected_fund_id), None)
        if not fund:
            return
        n_movs = len(portfolio.movements(fund["id"]))
        question = f"¿Seguro que quieres quitar «{fund['name']}» del seguimiento?"
        if n_movs:
            question += f"\n\nTambién se borrarán sus {n_movs} aportación(es)/reembolso(s) apuntados."
        if _confirm_delete("Eliminar fondo", question, parent=self.root, colors=self.colors,
                           confirm_text="Sí, quitar"):
            store.remove_fund(fund["id"])
            portfolio.remove_fund(fund["id"])
            applog.info("Fondo eliminado: %s (%d movimientos)", fund["id"], n_movs)
            self.selected_fund_id = None
            self.reload_funds()

    # ---------- refresco ----------
    def _manual_refresh(self):
        self.status_label.configure(text="Actualizando...")
        threading.Thread(target=self._background_refresh, daemon=True).start()

    def _background_refresh(self):
        funds = store.list_funds()
        errors = []

        def on_progress(fund, error):
            if error:
                errors.append(fund["name"])
                applog.log_exception("Fallo al actualizar el fondo %s", fund["name"])

        try:
            data_fetcher.refresh_all(funds, on_progress=on_progress)
        except Exception:
            applog.log_exception("Fallo general al actualizar los fondos")
        self._last_refresh = dt.datetime.now()
        now = self._last_refresh.strftime("%d/%m/%Y %H:%M")
        if errors:
            msg = f"Última actualización: {now}\nFallo en: {', '.join(errors)}"
        else:
            msg = f"Última actualización: {now}"
        self._ui_queue.put(("status", msg))
        self._ui_queue.put(("redraw", None))
        self._ui_queue.put(("alerts", None))

    def _check_alerts(self):
        """Tras cada actualización: avisa (una sola vez) de las caídas que pasen de lo
        que el usuario activo ha elegido en Configuración → Alertas de caídas."""
        try:
            new = alerts.check(store.list_funds(), lambda fid: data_fetcher.load_history(fid)["Close"],
                               settings.get_alerts())
        except Exception:
            applog.log_exception("Fallo comprobando las alertas de caída")
            return
        for a in new:
            applog.info("ALERTA (%s) %s: %.2f %% (VL %s -> %s, del %s)", a["kind"], a["name"], a["pct"],
                        a["from_nav"], a["to_nav"], a["to_date"])
        if new:
            self.tray.notify(*_alert_notification(new))

    def _start_scheduler(self):
        def loop():
            self._background_refresh()
            while True:
                threading.Event().wait(config.REFRESH_INTERVAL_SECONDS)
                self._background_refresh()

        threading.Thread(target=loop, daemon=True).start()

    def _poll_ui_queue(self):
        try:
            # Otra copia de MisFondos (doble clic en el acceso directo con este ya
            # abierto) pide mostrar la ventana en vez de abrir un segundo programa.
            if system.take_show_request():
                self._show_window()
            while True:
                kind, payload = self._ui_queue.get_nowait()
                if kind == "tray":  # menú del icono junto al reloj
                    if payload == "mostrar":
                        self._show_window()
                    elif payload == "actualizar":
                        self._manual_refresh()
                    elif payload == "salir":
                        self._quit()
                        return  # la ventana ya no existe: no se reprograma el sondeo
                    continue
                if kind == "alerts":  # no toca la interfaz: nunca se descarta
                    self._check_alerts()
                    continue
                if self._rebuilding:
                    continue  # se descarta: la interfaz se está reconstruyendo (cambio de tema)
                if kind == "status":
                    self.status_label.configure(text=payload)
                elif kind == "redraw":
                    self._redraw()
        except queue.Empty:
            pass
        except Exception:
            applog.log_exception("Fallo procesando la cola de actualizaciones de la UI")
        # 250ms: la respuesta a un clic en el icono del reloj depende de este sondeo.
        self.root.after(250, self._poll_ui_queue)

    # ---------- dibujado ----------
    def _style_axes(self, ax, max_ticks=None):
        """Estilo común de una gráfica. `max_ticks` limita las fechas del eje X en
        las gráficas pequeñas de la vista multi (si no, se pisan unas con otras)."""
        c = self.colors
        ax.clear()
        # El anillo del reparto quita los ejes y fija aspecto 1:1; se restauran aquí.
        ax.set_axis_on()
        ax.set_aspect("auto")
        ax.set_facecolor(c["bg_card"])
        ax.tick_params(colors=c["text_muted"], labelsize=8 if max_ticks else 9)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.grid(True, color=c["grid"], linewidth=0.6, axis="y")
        if max_ticks:
            ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=2, maxticks=max_ticks))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))

    def _make_hover_artists(self, ax):
        """Punto y bocadillo del tooltip de una gráfica, ocultos hasta pasar el ratón.
        Se crean en cada redibujado: ax.clear() / fig.clear() borran los anteriores."""
        c = self.colors
        (dot,) = ax.plot([], [], marker="o", markersize=6, linestyle="none",
                         color=c["text_primary"], zorder=5, visible=False)
        ann = ax.annotate(
            "", xy=(0, 0), xytext=(14, 14), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.5", fc=c["bg_card_hover"], ec=c["border"], lw=1),
            color=c["text_primary"], fontsize=9, visible=False, zorder=6,
        )
        return dot, ann

    def _use_single_axes(self):
        """Vuelve a una sola gráfica si antes estaba la vista multi (que las borró)."""
        if self.fig.axes != [self.ax]:
            self.fig.clear()
            self.ax = self.fig.add_subplot(111)

    def _redraw(self):
        if self._rebuilding:
            return
        try:
            self._plot_series = []
            self._pie_wedges = []
            self._multi_panels = []
            self._indicator = None
            funds = store.list_funds()

            mode = self.view_mode.get()
            if mode == "multi":
                self._hover_dot = self._hover_ann = None  # eran de la gráfica única, ya borrada
                self._draw_multi(funds)
            else:
                self._use_single_axes()
                self._style_axes(self.ax)
                if mode == "individual":
                    self._draw_individual(funds)
                elif mode == "global":
                    self._draw_global(funds)
                elif mode == "reparto":
                    self._draw_allocation(funds)
                else:
                    self._render_returns_table(funds)
                self._hover_dot, self._hover_ann = self._make_hover_artists(self.ax)
            self._update_header()
            self._update_portfolio_strip()
            self._update_tray_title()

            if mode == "multi":
                self._layout_multi()
            elif mode == "reparto":
                # Anillo a la izquierda y leyenda a la derecha (fuera del eje):
                # tight_layout no reserva sitio para una leyenda exterior.
                self.fig.subplots_adjust(left=0.02, right=0.52, top=0.9, bottom=0.06)
            else:
                self.fig.tight_layout()
            self.canvas.draw_idle()
        except Exception:
            applog.log_exception("Fallo al redibujar la gráfica")

    def _on_chart_resize(self, _event):
        """Al cambiar el tamaño de la ventana, los nombres de la vista multi se
        vuelven a recortar al ancho nuevo de cada gráfica."""
        if self._rebuilding or self.view_mode.get() != "multi" or not self._multi_panels:
            return
        try:
            self._layout_multi()
        except Exception:
            applog.log_exception("Fallo al recolocar la vista de varias gráficas")

    def _on_leave_chart(self, _event):
        if self._rebuilding:
            return
        try:
            self._hide_hover()
        except Exception:
            applog.log_exception("Fallo al ocultar el tooltip de la gráfica")

    def _hide_hover(self):
        changed = False
        pairs = [(self._hover_ann, self._hover_dot)] + [(p["ann"], p["dot"]) for p in self._multi_panels]
        for ann, dot in pairs:
            if ann is not None and ann.get_visible():
                ann.set_visible(False)
                dot.set_visible(False)
                changed = True
        if changed:
            self.canvas.draw_idle()

    def _place_hover(self, ax, ann, dot, x, y, color, text, x_cursor):
        """Muestra el bocadillo junto al punto (x, y), siempre hacia el centro de la
        gráfica para que no se salga por el borde."""
        ann.set_text(text)
        ann.xy = (x, y)
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        dx = 14 if x_cursor < (xlim[0] + xlim[1]) / 2 else -14
        dy = 14 if y < (ylim[0] + ylim[1]) / 2 else -14
        ann.xyann = (dx, dy)
        ann.set_ha("left" if dx > 0 else "right")
        ann.set_va("bottom" if dy > 0 else "top")
        ann.set_visible(True)
        dot.set_data([x], [y])
        dot.set_color(color)
        dot.set_visible(True)

    def _on_hover(self, event):
        if self._rebuilding:
            return
        try:
            self._do_hover(event)
        except Exception:
            applog.log_exception("Fallo en el tooltip de la gráfica")

    def _do_hover(self, event):
        if self.view_mode.get() == "multi":
            self._hover_multi(event)
            return
        if self._hover_ann is not None and self.view_mode.get() == "reparto":
            self._hover_pie(event)
            return
        if not self._plot_series or self._hover_ann is None or event.inaxes != self.ax or event.xdata is None:
            self._hide_hover()
            return

        x_cursor = event.xdata
        lines = []
        ref_num = None
        dot_x = dot_y = dot_color = None
        for series in self._plot_series:
            xnum = series["xnum"]
            if len(xnum) == 0:
                continue
            idx = (abs(xnum - x_cursor)).argmin()
            value = series["values"][idx]
            if ref_num is None:
                ref_num = xnum[idx]
                dot_x, dot_y, dot_color = xnum[idx], value, series["color"]
            normalized = self.view_mode.get() == "global" and self.normalize_var.get()
            lines.append(f"{series['label']}: {_fmt_es(value, 2 if normalized else _nav_decimals(value))}")

        if ref_num is None:
            self._hide_hover()
            return

        header = mdates.num2date(ref_num).strftime("%d %b %Y")
        self._place_hover(self.ax, self._hover_ann, self._hover_dot, dot_x, dot_y, dot_color,
                          header + "\n" + "\n".join(lines), x_cursor)
        self.canvas.draw_idle()

    def _hover_multi(self, event):
        """Tooltip de la vista multi: solo en la gráfica que está bajo el ratón."""
        panel = next((p for p in self._multi_panels if p["ax"] is event.inaxes), None)
        changed = False
        for p in self._multi_panels:
            if p is not panel and p["ann"].get_visible():
                p["ann"].set_visible(False)
                p["dot"].set_visible(False)
                changed = True
        series = panel["series"] if panel else None
        if series is None or event.xdata is None or len(series["xnum"]) == 0:
            if changed:
                self.canvas.draw_idle()
            return
        idx = (abs(series["xnum"] - event.xdata)).argmin()
        x, y = series["xnum"][idx], series["values"][idx]
        text = f"{mdates.num2date(x):%d %b %Y}\n{_fmt_es(y, _nav_decimals(y))}"
        # La gráfica activa se dibuja la última: si el bocadillo asoma sobre la de
        # al lado, queda por encima de ella y no tapado por su fondo.
        for p in self._multi_panels:
            p["ax"].set_zorder(1 if p is panel else 0)
        self._place_hover(panel["ax"], panel["ann"], panel["dot"], x, y, series["color"], text, event.xdata)
        self.canvas.draw_idle()

    def _draw_individual(self, funds):
        c = self.colors
        fund = next((f for f in funds if f["id"] == self.selected_fund_id), None)
        if not fund:
            self.ax.text(0.5, 0.5, "Añade un fondo para empezar", color=c["text_muted"], ha="center", va="center")
            return
        df = data_fetcher.load_history(fund["id"])
        if df.empty:
            self.ax.text(0.5, 0.5, "Sin datos todavía", color=c["text_muted"], ha="center", va="center")
            return
        start = _period_start(df, self.period.get())
        view = df[df.index >= start] if start is not None else df
        self.ax.plot(view.index, view["Close"], color=fund["color"], linewidth=2.4)
        self.ax.fill_between(view.index, view["Close"], view["Close"].min(), color=fund["color"], alpha=0.08)
        self.ax.set_title(fund["name"], color=c["text_primary"], fontsize=14, loc="left", fontweight="bold", pad=12)
        self._plot_series.append({
            "label": fund["name"], "color": fund["color"],
            "xnum": mdates.date2num(view.index.to_pydatetime()), "values": view["Close"].to_numpy(),
        })

        # Marcas de mis aportaciones (▲) y reembolsos (▼) dentro del periodo visible.
        first_visible = view.index.min()
        for kind, marker, color in ((portfolio.APORTACION, "^", c["up"]), (portfolio.REEMBOLSO, "v", c["down"])):
            xs, ys = [], []
            for m in portfolio.movements(fund["id"]):
                if m["kind"] != kind:
                    continue
                when = pd.Timestamp(m["date"])
                nav = portfolio.nav_on(df["Close"], when.date())
                if nav is None or when < first_visible.normalize():
                    continue
                xs.append(when)
                ys.append(nav)
            if xs:
                self.ax.scatter(xs, ys, marker=marker, s=90, color=color, edgecolors=c["bg_card"],
                                linewidths=1.2, zorder=4)

        # Último movimiento = penúltimo vs último valor del histórico completo (no del
        # periodo visible, que no cambia lo que ha pasado desde el dato anterior).
        closes = df["Close"].dropna()
        if len(closes) >= 2:
            period_pct = metrics.period_return(closes, self.period.get())
            self._indicator = {
                "prev": float(closes.iloc[-2]), "prev_date": closes.index[-2],
                "last": float(closes.iloc[-1]), "last_date": closes.index[-1],
                "period_pct": period_pct,
            }

    def _draw_allocation(self, funds):
        """Anillo con el peso de cada fondo según el valor actual de mis aportaciones."""
        c = self.colors
        self.ax.set_axis_off()
        items, currencies = [], set()
        for f in funds:
            closes = data_fetcher.load_history(f["id"])["Close"].dropna()
            pos = portfolio.position(f["id"], closes)
            if not pos or not pos["value"] or pos["value"] <= 0:
                continue
            items.append((f, pos))
            currencies.add((f.get("currency") or "EUR").upper())
        self.ax.set_title("Reparto de la cartera", color=c["text_primary"], fontsize=14, loc="left",
                          fontweight="bold", pad=12)
        if not items:
            self.ax.text(0.5, 0.5, "Apunta tus aportaciones en cada fondo (botón «Mis aportaciones»\n"
                                   "en la pestaña Fondo individual) para ver cómo se reparte tu cartera.",
                         color=c["text_muted"], ha="left", va="center", transform=self.ax.transAxes)
            return

        items.sort(key=lambda it: it[1]["value"], reverse=True)
        total = sum(p["value"] for _, p in items)
        cur = next(iter(currencies)) if len(currencies) == 1 else "EUR"
        wedges, _texts = self.ax.pie(
            [p["value"] for _, p in items], colors=[f["color"] for f, _ in items],
            startangle=90, counterclock=False,
            wedgeprops=dict(width=0.36, edgecolor=c["bg_card"], linewidth=2),
        )
        self.ax.set_aspect("equal")
        self.ax.text(0, 0.13, "Total", ha="center", va="center", color=c["text_muted"], fontsize=11)
        self.ax.text(0, -0.08, _money(total, cur), ha="center", va="center", color=c["text_primary"],
                     fontsize=16, fontweight="bold")

        labels = []
        for (f, p), wedge in zip(items, wedges):
            share = p["value"] / total * 100
            name = f["name"] if len(f["name"]) <= 34 else f["name"][:33] + "…"
            labels.append(f"{name}\n{_money(p['value'], cur)}   ·   {_fmt_es(share, 1)} %")
            info = f"{f['name']}\nValor: {_money(p['value'], cur)} ({_fmt_es(share, 1)} % de la cartera)" \
                   f"\nInvertido: {_money(p['invested'], cur)}"
            if p["gain"] is not None:
                pct = f" ({_signed(p['gain_pct'], _fmt_es(p['gain_pct'], 2))} %)" if p["gain_pct"] is not None else ""
                info += f"\nGanancia: {_signed(p['gain'], _money(p['gain'], cur))}{pct}"
            self._pie_wedges.append((wedge, info))

        legend = self.ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(1.04, 0.5), frameon=False,
                                fontsize=11, labelspacing=1.2, handlelength=1.1, handleheight=1.1)
        for text in legend.get_texts():
            text.set_color(c["text_primary"])
        if len(currencies) > 1:
            self.ax.text(0.0, -0.04, f"⚠ Mezcla divisas ({', '.join(sorted(currencies))}) sin convertir",
                         color=c["text_muted"], fontsize=9, transform=self.ax.transAxes)

    def _hover_pie(self, event):
        hit = None
        if event.inaxes == self.ax:
            hit = next((info for wedge, info in self._pie_wedges if wedge.contains(event)[0]), None)
        if hit is None or event.xdata is None:
            self._hide_hover()
            return
        self._hover_ann.set_text(hit)
        self._hover_ann.xy = (event.xdata, event.ydata)
        dx = 14 if event.xdata < 0 else -14
        dy = 14 if event.ydata < 0 else -14
        self._hover_ann.xyann = (dx, dy)
        self._hover_ann.set_ha("left" if dx > 0 else "right")
        self._hover_ann.set_va("bottom" if dy > 0 else "top")
        self._hover_ann.set_visible(True)
        self.canvas.draw_idle()

    def _draw_global(self, funds):
        c = self.colors
        if not funds:
            self.ax.text(0.5, 0.5, "Añade fondos para ver la vista global", color=c["text_muted"], ha="center", va="center")
            return
        any_data = False
        for fund in funds:
            df = data_fetcher.load_history(fund["id"])
            if df.empty:
                continue
            start = _period_start(df, self.period.get())
            view = df[df.index >= start] if start is not None else df
            if view.empty:
                continue
            series = view["Close"]
            if self.normalize_var.get():
                series = series / series.iloc[0] * 100
            self.ax.plot(view.index, series, color=fund["color"], linewidth=2.2, label=fund["name"])
            self._plot_series.append({
                "label": fund["name"], "color": fund["color"],
                "xnum": mdates.date2num(view.index.to_pydatetime()), "values": series.to_numpy(),
            })
            any_data = True
        if any_data:
            legend = self.ax.legend(
                loc="upper left", facecolor=c["bg_card_hover"], edgecolor="none", framealpha=0.9, fontsize=9
            )
            for text in legend.get_texts():
                text.set_color(c["text_primary"])
            self.ax.set_title(
                "Evolución comparada (base 100)" if self.normalize_var.get() else "Evolución comparada",
                color=c["text_primary"], fontsize=14, loc="left", fontweight="bold", pad=12,
            )
        else:
            self.ax.text(0.5, 0.5, "Sin datos todavía", color=c["text_muted"], ha="center", va="center")

    def _draw_multi(self, funds):
        """Las N primeras gráficas de la lista a la vez, en 2 filas. Con un número
        par, todas del mismo tamaño. Con uno impar, la que más rentabilidad da en el
        periodo elegido ocupa la columna de la izquierda entera (el doble que las
        demás) y el resto se reparte a partes iguales: 3 → 1 grande + 2, 5 → 1 + 4."""
        c = self.colors
        period = self.period.get()
        self.fig.clear()
        items = []
        for f in funds[:self.multi_count]:
            df = data_fetcher.load_history(f["id"])
            closes = df["Close"].dropna() if not df.empty else None
            items.append({"fund": f, "df": df, "ret": metrics.period_return(closes, period)})
        self._multi_info = (len(items), len(funds))
        if not items:
            ax = self.fig.add_subplot(111)
            self._style_axes(ax)
            ax.set_axis_off()
            ax.text(0.5, 0.5, "Añade fondos para ver varias gráficas a la vez", color=c["text_muted"],
                    ha="center", va="center", transform=ax.transAxes)
            return

        n = len(items)
        rows, cols = (1, n) if n <= 2 else (2, (n + 1) // 2)
        grid = self.fig.add_gridspec(rows, cols)
        big = None
        if n >= 3 and n % 2:
            # La de más rentabilidad; las que no tienen dato cuentan como las peores
            # y, a igualdad, gana la primera de la lista.
            big = max(items, key=lambda it: (it["ret"] is not None, it["ret"] or 0.0))
            ordered = [big] + [it for it in items if it is not big]
            cells = [grid[:, 0]] + [grid[r, k] for r in range(rows) for k in range(1, cols)]
        else:
            ordered = items
            cells = [grid[r, k] for r in range(rows) for k in range(cols)]
        max_ticks = 5 if cols <= 2 else 4
        for item, cell in zip(ordered, cells):
            self._draw_panel(self.fig.add_subplot(cell), item, item is big, max_ticks)

    def _draw_panel(self, ax, item, big, max_ticks):
        """Una gráfica de la vista multi: nombre a la izquierda y rentabilidad del
        periodo a la derecha (el nombre se recorta luego en _layout_multi)."""
        c = self.colors
        fund, df = item["fund"], item["df"]
        self._style_axes(ax, max_ticks=max_ticks)
        size = 13 if big else 11
        name = fund["name"].strip()
        title = ax.set_title(name, loc="left", color=c["text_primary"], fontsize=size, fontweight="bold", pad=8)
        if item["ret"] is None:
            ret_text, ret_color = "—", c["text_muted"]
        else:
            arrow, ret_color = self._direction_style(item["ret"])
            ret_text = f"{arrow} {_fmt_pct(item['ret'])}"
        ret_title = ax.set_title(ret_text, loc="right", color=ret_color, fontsize=size - 1, fontweight="bold", pad=8)

        series = None
        if df.empty:
            ax.text(0.5, 0.5, "Sin datos todavía", color=c["text_muted"], ha="center", va="center",
                    transform=ax.transAxes)
        else:
            start = _period_start(df, self.period.get())
            view = df[df.index >= start] if start is not None else df
            ax.plot(view.index, view["Close"], color=fund["color"], linewidth=2.2 if big else 1.8)
            ax.fill_between(view.index, view["Close"], view["Close"].min(), color=fund["color"], alpha=0.08)
            series = {
                "color": fund["color"],
                "xnum": mdates.date2num(view.index.to_pydatetime()), "values": view["Close"].to_numpy(),
            }
        dot, ann = self._make_hover_artists(ax)
        self._multi_panels.append({"ax": ax, "name": name, "title": title, "ret_title": ret_title,
                                   "series": series, "dot": dot, "ann": ann, "big": big})

    def _layout_multi(self):
        """Reparte el hueco entre las gráficas y recorta cada nombre con "…" para que
        quepa junto a su rentabilidad (depende del tamaño de la ventana)."""
        panels = self._multi_panels
        # Se colocan con un nombre corto de la misma altura: si no, un nombre largo
        # desborda su gráfica y tight_layout encoge todas para hacerle sitio.
        for p in panels:
            p["title"].set_text("Ag")
        self.fig.tight_layout(h_pad=1.5, w_pad=2.5)
        if not panels:
            return
        renderer = self.canvas.get_renderer()
        gap = 10 * self.fig.dpi / 72  # 10 pt entre el nombre y la rentabilidad
        for p in panels:
            room = (p["ax"].get_window_extent(renderer).width
                    - p["ret_title"].get_window_extent(renderer).width - gap)
            _fit_mpl_text(p["title"], p["name"], room, renderer)


def run():
    applog.setup()
    start_hidden = system.MINIMIZED_ARG in sys.argv[1:]
    if not system.acquire_single_instance():
        # Ya hay un MisFondos en marcha (quizá escondido junto al reloj): se le pide
        # que se muestre y esta copia se cierra. Con --minimizado (arranque con
        # Windows) no se le molesta: ya está donde tiene que estar.
        applog.info("Ya había un MisFondos en marcha: %s", "se deja igual" if start_hidden else "se le pide mostrarse")
        if not start_hidden:
            system.request_show_existing()
        return
    root = ctk.CTk()
    if start_hidden:
        root.withdraw()  # arranque con Windows: directo junto al reloj, sin que parpadee la ventana
    applog.install_tk_hook(root)
    app = MisFondosApp(root)
    if start_hidden and not app.tray.running:
        root.deiconify()  # sin icono junto al reloj no habría forma de abrirlo
    root.mainloop()
