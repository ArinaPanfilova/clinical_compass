"""Запуск: python -m server  →  http://localhost:8000 (API под /api, интерфейс — собранный frontend/dist).

Переменные окружения:
  KOMPAS_DB                 путь к БД (data/kompas.db); при первом запуске заполняется демо-данными
  KOMPAS_SECRET             секрет подписи токенов (обязательно сменить вне демо)
  KOMPAS_ESCALATE_AFTER_S   через сколько секунд непринятый срочный алерт уходит заместителю (60)
  KOMPAS_DEMO               1 — разрешён /api/demo/reset (1)
  KOMPAS_WORKERS            число процессов (4); алерты между процессами доставляются через БД
  KOMPAS_HOST, KOMPAS_PORT  адрес сервера (0.0.0.0:8000)
"""
import os

import uvicorn

from .app import app_from_env, prepare_db


def main() -> None:
    prepare_db(os.environ.get("KOMPAS_DB", "data/kompas.db"))      # один раз, до запуска воркеров
    host, port = os.environ.get("KOMPAS_HOST", "0.0.0.0"), int(os.environ.get("KOMPAS_PORT", "8000"))
    workers = int(os.environ.get("KOMPAS_WORKERS", "4"))
    if workers > 1:
        uvicorn.run("server.app:app_from_env", factory=True, workers=workers, host=host, port=port,
                    timeout_graceful_shutdown=3)
    else:
        uvicorn.run(app_from_env(), host=host, port=port, timeout_graceful_shutdown=3)


if __name__ == "__main__":
    main()
