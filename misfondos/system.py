"""Integración con Windows: una sola copia abierta a la vez y arranque con Windows.

- Una sola copia: un mutex con nombre. Si al arrancar ya existe (MisFondos sigue
  funcionando junto al reloj), la copia nueva deja un fichero de aviso en data/ y
  se cierra; la que ya estaba lo ve en su sondeo periódico y muestra su ventana.
  El nombre del mutex incluye la carpeta del programa, para que una copia de
  pruebas en otra carpeta no choque con la instalada.
- Arranque con Windows: valor en HKCU\\...\\CurrentVersion\\Run (lo muestra y
  permite desactivarlo también el Administrador de tareas, pestaña Inicio).
"""
import ctypes
import hashlib
import os
import sys
import winreg

from . import config

MINIMIZED_ARG = "--minimizado"
SHOW_FLAG = os.path.join(config.DATA_DIR, ".mostrar")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "MisFondos"

_ERROR_ALREADY_EXISTS = 183
_mutex_handle = None


def acquire_single_instance():
    """True si esta es la única copia en marcha (y la reserva hasta que termine)."""
    global _mutex_handle
    tag = hashlib.sha1(config.APP_DIR.lower().encode("utf-8")).hexdigest()[:12]
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, f"Local\\MisFondos_{tag}")
    if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return False
    _mutex_handle = handle  # se libera solo al terminar el proceso
    return True


def request_show_existing():
    """Pide a la copia que ya está en marcha que muestre su ventana."""
    with open(SHOW_FLAG, "w", encoding="utf-8") as f:
        f.write("mostrar")
    # Esta copia la ha lanzado el usuario, así que tiene permiso para poner ventanas
    # en primer plano; se lo cede a la otra, o Windows solo haría parpadear su botón.
    ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY


def take_show_request():
    """True (una sola vez) si otra copia ha pedido mostrar la ventana."""
    if os.path.exists(SHOW_FLAG):
        try:
            os.remove(SHOW_FLAG)
        except OSError:
            pass
        return True
    return False


def autostart_supported():
    # Solo tiene sentido con el .exe instalado; desde el código fuente, el comando
    # a lanzar sería python + run.py.
    return getattr(sys, "frozen", False)


def _autostart_command():
    return f'"{sys.executable}" {MINIMIZED_ARG}'


def is_autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE)
        return bool(value)
    except OSError:
        return False


def set_autostart(enabled, command=None):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, command or _autostart_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
