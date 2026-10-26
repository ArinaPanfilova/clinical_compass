"""Запуск сервера «Компаса» отдельным процессом на временной БД — для замеров технических метрик."""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, db: Path, port: int | None = None, escalate_after_s: float = 600, workers: int = 1):
        self.db, self.port = Path(db), port or free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.env = {**os.environ, "KOMPAS_DB": str(self.db), "KOMPAS_PORT": str(self.port),
                    "KOMPAS_HOST": "127.0.0.1", "KOMPAS_ESCALATE_AFTER_S": str(escalate_after_s),
                    "KOMPAS_WORKERS": str(workers)}
        self.proc: subprocess.Popen | None = None

    def start(self, timeout: float = 30) -> float:
        """Запускает процесс и ждёт /api/health. Возвращает время до готовности, с."""
        t0 = time.perf_counter()
        self.proc = subprocess.Popen([sys.executable, "-m", "server"], cwd=ROOT, env=self.env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while time.perf_counter() - t0 < timeout:
            try:
                if httpx.get(f"{self.url}/api/health", timeout=0.5).status_code == 200:
                    return time.perf_counter() - t0
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        raise RuntimeError("сервер не поднялся")

    def kill(self) -> None:
        """Аварийная остановка: SIGKILL, без корректного завершения."""
        if self.proc:
            self.proc.send_signal(signal.SIGKILL)
            self.proc.wait()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(8)
            except subprocess.TimeoutExpired:      # открытые SSE-потоки не дают завершиться мягко
                self.proc.kill()
                self.proc.wait()


def login(url: str, user: str) -> dict:
    r = httpx.post(f"{url}/api/auth/login", json={"login": user, "password": "demo"})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)
