"""Запуск: python -m server  →  http://localhost:8000 (API под /api, интерфейс — собранный frontend/dist).

Переменные окружения:
  KOMPAS_DB                 путь к БД (data/kompas.db); при первом запуске заполняется демо-данными
  KOMPAS_SECRET             секрет подписи токенов (обязательно сменить вне демо)
  KOMPAS_ESCALATE_AFTER_S   через сколько секунд непринятый срочный алерт уходит заместителю (60)
  KOMPAS_DEMO               1 — разрешён /api/demo/reset (1)
  KOMPAS_HOST, KOMPAS_PORT  адрес сервера (0.0.0.0:8000)
"""
import os

import uvicorn

from .app import create_app


def main() -> None:
    app = create_app(os.environ.get("KOMPAS_DB", "data/kompas.db"),
                     secret=os.environ.get("KOMPAS_SECRET", "dev-secret-change-me"),
                     escalate_after_s=float(os.environ.get("KOMPAS_ESCALATE_AFTER_S", "60")),
                     demo=os.environ.get("KOMPAS_DEMO", "1") == "1")
    uvicorn.run(app, host=os.environ.get("KOMPAS_HOST", "0.0.0.0"), port=int(os.environ.get("KOMPAS_PORT", "8000")))


if __name__ == "__main__":
    main()
