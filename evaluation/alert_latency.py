"""Время доставки алерта: от отправки самоотчёта пациентом до получения сигнала клиентом врача.

Метрика ТЗ №1 («время доставки алерта врачу с момента поступления критических данных»).
Цикл: пациент отправляет PHQ-9 с п.9 = 2 → сервер в одной транзакции сохраняет данные и создаёт
алерт → клиент врача получает его по SSE и подтверждает (ack) → врач закрывает решением, чтобы
следующий самоотчёт создал новый алерт.

    python evaluation/alert_latency.py --n 100 --workers 4
"""
from __future__ import annotations

import argparse
import json
import queue
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation._server import Server, login, pct  # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
REPORT = {"questionnaires": [{"scale": "phq9", "answers": [1] * 8 + [2]}]}


def listen(url: str, token: str, inbox: queue.Queue, stop: threading.Event) -> None:
    with httpx.stream("GET", f"{url}/api/events/stream", params={"token": token}, timeout=None) as r:
        event = None
        for line in r.iter_lines():
            if stop.is_set():
                return
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event == "alert":
                inbox.put((time.perf_counter(), json.loads(line[6:])))


def ms(a: str, b: str) -> float:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() * 1000


def run(n: int, workers: int) -> dict:
    with tempfile.TemporaryDirectory() as d:
        srv = Server(Path(d) / "lat.db", workers=workers)
        srv.start()
        try:
            doc, pat = login(srv.url, "ivanova"), login(srv.url, "anna")
            inbox: queue.Queue = queue.Queue()
            stop = threading.Event()
            threading.Thread(target=listen, args=(srv.url, doc["Authorization"][7:], inbox, stop), daemon=True).start()
            time.sleep(1)
            e2e, create, lost = [], [], 0
            with httpx.Client(base_url=srv.url, timeout=10) as c:
                for _ in range(n):
                    t0 = time.perf_counter()
                    r = c.post("/api/patients/P-001/self-report", json=REPORT,
                               headers={**pat, "Idempotency-Key": uuid.uuid4().hex}).json()
                    want = set(r["alerts_created"])
                    got = None
                    while want and time.perf_counter() - t0 < 5:
                        try:
                            t, a = inbox.get(timeout=0.2)
                        except queue.Empty:
                            continue
                        if a["id"] in want:
                            got = (t, a)
                            break
                    if not got:
                        lost += 1
                    else:
                        t, a = got
                        e2e.append((t - t0) * 1000)
                        create.append(ms(a["saved_at"], a["created_at"]))
                        c.post(f"/api/alerts/{a['id']}/ack", headers=doc)
                    c.post("/api/patients/P-001/decisions", headers=doc,
                           json={"finding_rule_id": "SAFE-002", "action": "confirm"})
            stop.set()
        finally:
            srv.stop()
    stat = lambda xs: {"p50": round(pct(xs, 50), 1), "p95": round(pct(xs, 95), 1), "max": round(max(xs), 1)}
    return {"n": n, "workers": workers, "lost": lost, "saved_to_created_ms": stat(create),
            "patient_send_to_doctor_client_ms": stat(e2e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    a = ap.parse_args()
    results = [run(a.n, 1), run(a.n, 4)]
    OUT.mkdir(exist_ok=True)
    (OUT / "alert_latency.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# Время доставки алерта врачу", "",
             "Пациент отправляет PHQ-9 с п.9 = 2 → алерт создаётся в той же транзакции, что и данные → "
             "клиент врача получает его по SSE. Клиент и сервер на одной машине, без внешней сети.", "",
             "| Процессов | n | Потеряно | Сохранено → алерт создан, мс (p50 / p95 / max) | "
             "Отправка пациентом → получено врачом, мс (p50 / p95 / max) |", "|---|---|---|---|---|"]
    for r in results:
        c, e = r["saved_to_created_ms"], r["patient_send_to_doctor_client_ms"]
        lines.append(f"| {r['workers']} | {r['n']} | {r['lost']} | {c['p50']} / {c['p95']} / {c['max']} | "
                     f"{e['p50']} / {e['p95']} / {e['max']} |")
    lines += ["", "При нескольких процессах алерт, созданный в соседнем процессе, доходит через проверку БД (не реже раза в 0,5 с), "
              "иначе — сразу через брокер процесса. Цели прототипа (проектный документ, 13.4): создание ≤ 5 с, доставка ≤ 30 с.",
              "Время реакции человека — отдельный регламент, а не метрика программы."]
    (OUT / "alert_latency.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
