"""HTTP-сервер «Компаса»: роли, карточки пациентов, самоотчёты, алерты, сообщения, аналитика.

API — под префиксом /api; собранный фронтенд (frontend/dist), если есть, раздаётся с «/».
Клиническая логика — только в kompas_core; сервер хранит данные, проверяет права и доставляет алерты.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from kompas_core import ENGINE_VERSION, evaluate_patient

from . import access
from .auth import make_token, read_token, verify_password
from .db import connect, init_schema
from .records import build_record
from .seed import seed_demo

FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


class Login(BaseModel):
    login: str
    password: str


def _public_user(u) -> dict:
    return {"id": u["id"], "role": u["role"], "display_name": u["display_name"], "patient_id": u["patient_id"]}


def evaluate(record: dict) -> dict:
    t0 = time.perf_counter()
    ev = evaluate_patient(record, drugs=["aviandr"])
    ev["api_elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    return ev


def create_app(db_path: str | Path, secret: str = "dev-secret-change-me", escalate_after_s: float = 60,
               demo: bool = True, seed_courses: list[dict] | None = None, start_background: bool = True) -> FastAPI:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    def ensure_db() -> None:
        conn = connect(db_path)
        init_schema(conn)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            seed_demo(conn, courses=seed_courses)
        conn.close()

    ensure_db()
    app = FastAPI(title="Компас API", version=ENGINE_VERSION)
    api = APIRouter(prefix="/api")

    def get_conn() -> Iterator[sqlite3.Connection]:
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    def user_from_token(conn: sqlite3.Connection, token: str | None) -> dict:
        uid = read_token(token or "", secret)
        row = uid and conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if not row:
            raise HTTPException(401, "Требуется вход")
        return dict(row)

    def current_user(conn: sqlite3.Connection = Depends(get_conn),
                     authorization: str | None = Header(default=None)) -> dict:
        token = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
        return user_from_token(conn, token)

    def require_patient_access(conn: sqlite3.Connection, user: dict, pid: str, action: str) -> str:
        kind = access.link_kind(conn, user, pid)
        access.audit(conn, user, action, pid, kind is not None)
        if kind is None:
            raise HTTPException(403, "Нет доступа к данным этого пациента")
        return kind

    def bundle(conn: sqlite3.Connection, pid: str, link: str) -> dict:
        record = build_record(conn, pid)
        return {"record": record, "evaluation": evaluate(record), "link": link}

    @api.get("/health")
    def health(conn: sqlite3.Connection = Depends(get_conn)):
        conn.execute("SELECT 1").fetchone()
        return {"ok": True, "engine_version": ENGINE_VERSION}

    @api.post("/auth/login")
    def login(body: Login, conn: sqlite3.Connection = Depends(get_conn)):
        u = conn.execute("SELECT * FROM users WHERE login = ?", (body.login,)).fetchone()
        if not u or not verify_password(body.password, u["pwd_hash"]):
            access.audit(conn, None, f"login_failed:{body.login}", None, False)
            raise HTTPException(401, "Неверный логин или пароль")
        access.audit(conn, dict(u), "login", None, True)
        return {"token": make_token(u["id"], secret), "user": _public_user(u)}

    @api.get("/me")
    def me(user: dict = Depends(current_user)):
        return _public_user(user)

    @api.get("/patients")
    def list_patients(user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_conn)):
        if user["role"] != "doctor":
            access.audit(conn, user, "list_patients", None, False)
            raise HTTPException(403, "Список пациентов доступен только врачу")
        access.audit(conn, user, "list_patients", None, True)
        return [bundle(conn, pid, link) for pid, link in access.doctor_patients(conn, user["id"])]

    @api.get("/patients/{pid}")
    def get_patient(pid: str, user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_conn)):
        link = require_patient_access(conn, user, pid, "view_patient")
        return bundle(conn, pid, link)

    app.include_router(api)
    app.state.db_path = db_path
    return app
