"""Сквозные тесты интерфейса: настоящий сервер (python -m server) + собранный фронтенд + Chromium.

Запуск: python -m pytest e2e -q   (нужны `pip install playwright` и `playwright install chromium`)
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ESCALATE_AFTER_S = 4


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session", autouse=True)
def built_frontend():
    subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", check=True, capture_output=True)


@pytest.fixture
def server(tmp_path, built_frontend):
    port = _free_port()
    env = {**os.environ, "KOMPAS_DB": str(tmp_path / "e2e.db"), "KOMPAS_PORT": str(port),
           "KOMPAS_HOST": "127.0.0.1", "KOMPAS_ESCALATE_AFTER_S": str(ESCALATE_AFTER_S),
           "KOMPAS_WORKERS": "2"}
    proc = subprocess.Popen([sys.executable, "-m", "server"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{url}/api/health", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("сервер не поднялся")
    yield url
    proc.terminate()
    proc.wait(10)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def open_as(browser, server):
    """open_as('anna') → страница, на которой выполнен вход демо-аккаунтом."""
    contexts = []

    def _open(login: str):
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU")
        contexts.append(ctx)
        page = ctx.new_page()
        page.set_default_timeout(8000)
        page.goto(server)
        page.get_by_role("button", name=DEMO_BUTTONS[login]).click()
        # Дождаться ухода экрана входа: иначе следующий клик может попасть в другую демо-кнопку
        expect(page.get_by_role("heading", name="Вход в Компас")).to_have_count(0)
        return page

    yield _open
    for c in contexts:
        c.close()


DEMO_BUTTONS = {"ivanova": "Иванова Е. А.", "petrov": "Петров С. В.", "anna": "Анна К.",
                "alexey": "Алексей Н.", "maria": "Мария С.", "researcher": "Исследователь"}
