import logging
import os
import sys
import threading

from . import config

LOG_FILE = os.path.join(config.DATA_DIR, "misfondos_log.txt")

_configured = False


def setup():
    """Instala logging a fichero + gancho de excepciones no capturadas.
    Debe llamarse una sola vez, al arrancar la app."""
    global _configured
    if _configured:
        return
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
        encoding="utf-8",
    )
    logging.info("=== MisFondos iniciado ===")

    def _excepthook(exc_type, exc_value, exc_tb):
        logging.critical("Excepción no capturada", exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    if hasattr(threading, "excepthook"):
        def _thread_excepthook(args):
            logging.critical(
                "Excepción no capturada en hilo %s", args.thread.name,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

        threading.excepthook = _thread_excepthook

    _configured = True


def install_tk_hook(root):
    """Las excepciones lanzadas dentro de callbacks de Tkinter (botones, eventos)
    no llegan a sys.excepthook: Tkinter las captura y las ignora salvo que se
    sobreescriba este método."""

    def _report(exc_type, exc_value, exc_tb):
        logging.error("Excepción en callback de Tkinter", exc_info=(exc_type, exc_value, exc_tb))

    root.report_callback_exception = _report


def log_exception(msg, *args):
    logging.exception(msg, *args)


def info(msg, *args):
    logging.info(msg, *args)


def warning(msg, *args):
    logging.warning(msg, *args)
