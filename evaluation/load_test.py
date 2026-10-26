"""Нагрузочный тест: 100 одновременных сессий (80 пациентских, 20 врачебных) с паузами.

Профиль из проектного документа (раздел 13.5): p95 обычных экранов ≤ 2 с, правил ≤ 3 с, ошибок < 1 %.
Пациентских аккаунтов в демо 8 — сессии делят их; на сервер это даёт ту же нагрузку.
Каждый ответ проверяется по содержанию: HTTP 200 с неверным телом считается ошибкой.

    python evaluation/load_test.py --duration 60 --users 100
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation._server import Server, login, pct  # noqa: E402

PATIENTS = {"anna": "P-001", "sergey": "P-002", "olga": "P-003", "igor": "P-004",
            "maria": "P-005", "dmitry": "P-006", "elena": "P-007", "alexey": "P-008"}
OUT = Path(__file__).resolve().parent / "results"


async def patient_session(c: httpx.AsyncClient, h: dict, pid: str, until: float, rec):
    rnd = random.Random()
    while time.perf_counter() < until:
        action = rnd.choices(["card", "report", "intake", "messages"], [4, 2, 2, 2])[0]
        if action == "card":
            await rec("GET /patients/{id}", c.get(f"/api/patients/{pid}", headers=h),
                      lambda j: j["record"]["patient_id"] == pid and "evaluation" in j)
        elif action == "report":
            body = {"questionnaires": [{"scale": "gad7", "answers": [rnd.randint(0, 2) for _ in range(7)]}],
                    "diary_text": "нагрузочный тест"}
            await rec("POST self-report", c.post(f"/api/patients/{pid}/self-report", json=body, headers=h),
                      lambda j: "evaluation" in j and "saved_at" in j)
        elif action == "intake":
            await rec("POST intake", c.post(f"/api/patients/{pid}/intake", json={"status": "taken"}, headers=h),
                      lambda j: "adherence" in j)
        else:
            await rec("GET messages", c.get(f"/api/patients/{pid}/messages", headers=h), lambda j: isinstance(j, list))
        await asyncio.sleep(rnd.uniform(1, 3))


async def doctor_session(c: httpx.AsyncClient, h: dict, until: float, rec):
    rnd = random.Random()
    while time.perf_counter() < until:
        action = rnd.choices(["list", "card", "analytics", "alerts"], [3, 4, 1, 2])[0]
        if action == "list":
            await rec("GET /patients (список с правилами)", c.get("/api/patients", headers=h),
                      lambda j: len(j) >= 8 and all("evaluation" in b for b in j))
        elif action == "card":
            pid = rnd.choice(list(PATIENTS.values()))
            await rec("GET /patients/{id}", c.get(f"/api/patients/{pid}", headers=h),
                      lambda j: j["record"]["patient_id"] == pid)
        elif action == "analytics":
            await rec("GET analytics", c.get("/api/analytics/aviandr", headers=h), lambda j: j["n"] > 0)
        else:
            await rec("GET alerts", c.get("/api/alerts", headers=h), lambda j: isinstance(j, list))
        await asyncio.sleep(rnd.uniform(1, 3))


async def run(url: str, users: int, duration: float) -> dict:
    lat: dict[str, list[float]] = defaultdict(list)
    errors: dict[str, int] = defaultdict(int)

    async def rec(name, coro, check):
        t0 = time.perf_counter()
        try:
            r = await coro
            ok = r.status_code == 200 and check(r.json())
        except Exception:
            ok = False
        lat[name].append(time.perf_counter() - t0)
        if not ok:
            errors[name] += 1

    n_doc = users // 5
    heads_p = {u: login(url, u) for u in PATIENTS}
    heads_d = [login(url, "ivanova") for _ in range(n_doc)]
    until = time.perf_counter() + duration
    limits = httpx.Limits(max_connections=users + 10)
    async with httpx.AsyncClient(base_url=url, timeout=30, limits=limits) as c:
        tasks = [doctor_session(c, h, until, rec) for h in heads_d]
        logins = list(PATIENTS.items())
        tasks += [patient_session(c, heads_p[logins[i % 8][0]], logins[i % 8][1], until, rec)
                  for i in range(users - n_doc)]
        await asyncio.gather(*tasks)
    total = sum(len(v) for v in lat.values())
    return {
        "users": users, "doctors": n_doc, "patients": users - n_doc, "duration_s": duration,
        "requests": total, "rps": round(total / duration, 1),
        "errors": sum(errors.values()), "error_rate_pct": round(100 * sum(errors.values()) / max(total, 1), 3),
        "endpoints": {k: {"n": len(v), "p50_ms": round(pct(v, 50) * 1000, 1), "p95_ms": round(pct(v, 95) * 1000, 1),
                          "p99_ms": round(pct(v, 99) * 1000, 1), "errors": errors.get(k, 0)}
                      for k, v in sorted(lat.items())},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=100)
    ap.add_argument("--duration", type=float, default=60)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as d:
        srv = Server(Path(d) / "load.db", workers=a.workers)
        srv.start()
        try:
            res = asyncio.run(run(srv.url, a.users, a.duration))
        finally:
            srv.stop()
    res["machine"] = (f"{os.cpu_count()} потоков CPU, {a.workers} процессов uvicorn, общая SQLite (WAL), "
                      f"клиент и сервер на одной машине")
    OUT.mkdir(exist_ok=True)
    (OUT / "load_test.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# Нагрузочный тест: {res['users']} сессий ({res['patients']} пациентских, {res['doctors']} врачебных), "
             f"{res['duration_s']:.0f} с", "", f"Стенд: {res['machine']}.", "",
             f"Запросов: {res['requests']} ({res['rps']} в секунду), ошибок: {res['errors']} "
             f"({res['error_rate_pct']} %). Ошибкой считается и HTTP 200 с неверным содержимым.", "",
             "| Действие | n | p50, мс | p95, мс | p99, мс | ошибки |", "|---|---|---|---|---|---|"]
    lines += [f"| {k} | {v['n']} | {v['p50_ms']} | {v['p95_ms']} | {v['p99_ms']} | {v['errors']} |"
              for k, v in res["endpoints"].items()]
    lines += ["", "Цели прототипа (проектный документ, 13.5): p95 экранов ≤ 2000 мс, правил ≤ 3000 мс, ошибок < 1 %."]
    (OUT / "load_test.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
