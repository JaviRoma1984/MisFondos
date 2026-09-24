"""Icono de MisFondos junto al reloj de Windows (área de notificación).

pystray mantiene su propio bucle de mensajes de Windows en un hilo aparte. Sus
menús se ejecutan en ese hilo, así que aquí NUNCA se toca Tkinter: cada opción
solo deja una orden en la cola de la interfaz ("tray", "mostrar" / "actualizar" /
"salir") y es el sondeo de la ventana principal quien la ejecuta en su hilo.
"""
import threading

import pystray
from PIL import Image

from . import applog, config

# Windows corta el texto emergente del icono a 127 caracteres (szTip[128]).
_TITLE_MAX = 127


class TrayIcon:
    def __init__(self, ui_queue):
        self._queue = ui_queue
        self._icon = None

    def start(self):
        try:
            image = Image.open(config.LOGO_FILE)
            menu = pystray.Menu(
                # default=True: es la que se ejecuta con un clic normal sobre el icono
                pystray.MenuItem("Abrir MisFondos", self._on("mostrar"), default=True),
                pystray.MenuItem("Actualizar ahora", self._on("actualizar")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Salir", self._on("salir")),
            )
            self._icon = pystray.Icon("MisFondos", image, "MisFondos", menu)
            threading.Thread(target=self._run, name="bandeja", daemon=True).start()
            return True
        except Exception:
            applog.log_exception("No se pudo crear el icono junto al reloj")
            self._icon = None
            return False

    def _run(self):
        try:
            self._icon.run()
        except Exception:
            applog.log_exception("El icono junto al reloj se ha detenido por un error")

    def _on(self, command):
        def action(_icon, _item):
            self._queue.put(("tray", command))
        return action

    @property
    def running(self):
        return self._icon is not None

    def set_title(self, text):
        if not self._icon:
            return
        if len(text) > _TITLE_MAX:
            text = text[:_TITLE_MAX - 1] + "…"
        try:
            self._icon.title = text
        except Exception:
            applog.log_exception("No se pudo actualizar el texto del icono junto al reloj")

    def notify(self, message, title="MisFondos"):
        if not self._icon:
            return
        try:
            self._icon.notify(message, title)
        except Exception:
            applog.log_exception("No se pudo mostrar el aviso junto al reloj")

    def stop(self):
        if not self._icon:
            return
        try:
            self._icon.stop()
        except Exception:
            applog.log_exception("No se pudo quitar el icono junto al reloj")
        self._icon = None
