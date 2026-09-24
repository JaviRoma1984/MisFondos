"""Usuarios: cada uno con su propia lista de fondos, aportaciones y ajustes.

Estructura en disco (junto al .exe):
    data/users.json                 lista de usuarios y el usuario activo
    data/users/<id>/funds.json      fondos de ese usuario
    data/users/<id>/portfolio.json  sus aportaciones y reembolsos
    data/users/<id>/settings.json   sus ajustes (tema de colores, reglas de alertas)
    data/users/<id>/alerts.json     alertas ya avisadas y los últimos avisos
    data/history/<ISIN>.csv         histórico de VL, COMÚN a todos: el precio de un
                                    fondo es el mismo sea quien sea quien lo siga

Los módulos store/portfolio/settings leen config.FUNDS_FILE, etc. en cada
llamada, así que activar un usuario es simplemente apuntar esas rutas a su
carpeta.
"""
import json
import os
import shutil
import threading
import uuid

from . import applog, config

USERS_FILE = os.path.join(config.DATA_DIR, "users.json")
USERS_DIR = os.path.join(config.DATA_DIR, "users")
DEFAULT_NAME = "Principal"
MAX_NAME = 40
_PER_USER_FILES = ("funds.json", "portfolio.json", "settings.json")

_lock = threading.RLock()
_initialized = False


def _load():
    if not os.path.exists(USERS_FILE):
        return {"users": [], "current": None}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data):
    tmp = USERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, USERS_FILE)


def user_dir(user_id):
    return os.path.join(USERS_DIR, user_id)


def _point_config_to(user_id):
    folder = user_dir(user_id)
    os.makedirs(folder, exist_ok=True)
    config.FUNDS_FILE = os.path.join(folder, "funds.json")
    config.PORTFOLIO_FILE = os.path.join(folder, "portfolio.json")
    config.SETTINGS_FILE = os.path.join(folder, "settings.json")
    config.ALERTS_FILE = os.path.join(folder, "alerts.json")


def init():
    """Crea el primer usuario si no hay ninguno (moviendo a su carpeta los datos que
    hubiera de antes de existir los usuarios) y activa el último usuario usado."""
    global _initialized
    with _lock:
        if _initialized:
            return
        data = _load()
        if not data.get("users"):
            uid = _new_id()
            folder = user_dir(uid)
            os.makedirs(folder, exist_ok=True)
            moved = []
            for fname in _PER_USER_FILES:
                old = os.path.join(config.DATA_DIR, fname)
                if os.path.exists(old):
                    shutil.move(old, os.path.join(folder, fname))
                    moved.append(fname)
            data = {"users": [{"id": uid, "name": DEFAULT_NAME}], "current": uid}
            _save(data)
            applog.info("Creado el usuario inicial '%s' (%s); datos anteriores movidos: %s", DEFAULT_NAME, uid, moved)
        ids = [u["id"] for u in data["users"]]
        current = data.get("current") if data.get("current") in ids else ids[0]
        if current != data.get("current"):
            data["current"] = current
            _save(data)
        _point_config_to(current)
        _initialized = True


def _new_id():
    return "u" + uuid.uuid4().hex[:10]


def list_users():
    with _lock:
        return list(_load()["users"])


def current():
    with _lock:
        data = _load()
        return next((u for u in data["users"] if u["id"] == data.get("current")), None)


def _clean_name(name, others):
    name = " ".join((name or "").split())
    if not name:
        raise ValueError("Escribe un nombre para el usuario.")
    if len(name) > MAX_NAME:
        raise ValueError(f"El nombre no puede tener más de {MAX_NAME} caracteres.")
    if any(u["name"].casefold() == name.casefold() for u in others):
        raise ValueError(f"Ya existe un usuario llamado «{name}».")
    return name


def add_user(name):
    with _lock:
        data = _load()
        name = _clean_name(name, data["users"])
        user = {"id": _new_id(), "name": name}
        os.makedirs(user_dir(user["id"]), exist_ok=True)
        data["users"].append(user)
        _save(data)
        applog.info("Usuario añadido: '%s' (%s)", name, user["id"])
        return user


def rename_user(user_id, name):
    with _lock:
        data = _load()
        others = [u for u in data["users"] if u["id"] != user_id]
        name = _clean_name(name, others)
        for u in data["users"]:
            if u["id"] == user_id:
                u["name"] = name
        _save(data)
        applog.info("Usuario %s renombrado a '%s'", user_id, name)


def activate(user_id):
    with _lock:
        data = _load()
        if user_id not in [u["id"] for u in data["users"]]:
            raise ValueError("Ese usuario ya no existe.")
        data["current"] = user_id
        _save(data)
        _point_config_to(user_id)
        applog.info("Usuario activo: %s", user_id)


def delete_user(user_id):
    """Borra el usuario y TODOS sus datos (no el histórico de VL, que es común).
    Si es el activo, se activa otro. Si era el único, en su lugar se crea uno vacío
    llamado "Principal" (el programa siempre necesita un usuario activo) que conserva
    los colores elegidos, para que la ventana no cambie de aspecto de golpe."""
    with _lock:
        data = _load()
        user = next((u for u in data["users"] if u["id"] == user_id), None)
        if user is None:
            return
        data["users"] = [u for u in data["users"] if u["id"] != user_id]
        if not data["users"]:
            fresh = {"id": _new_id(), "name": DEFAULT_NAME}
            os.makedirs(user_dir(fresh["id"]), exist_ok=True)
            old_settings = os.path.join(user_dir(user_id), "settings.json")
            if os.path.exists(old_settings):
                shutil.copy2(old_settings, os.path.join(user_dir(fresh["id"]), "settings.json"))
            data["users"].append(fresh)
            applog.info("Era el único usuario: se crea uno vacío '%s' (%s)", DEFAULT_NAME, fresh["id"])
        if data.get("current") == user_id:
            data["current"] = data["users"][0]["id"]
            _point_config_to(data["current"])
        _save(data)
        shutil.rmtree(user_dir(user_id), ignore_errors=True)
        applog.info("Usuario borrado: '%s' (%s)", user["name"], user_id)
