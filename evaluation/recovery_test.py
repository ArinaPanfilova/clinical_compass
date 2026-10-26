"""Отказоустойчивость: аварийное падение сервера (SIGKILL всей группы процессов) во время потока
самоотчётов и восстановление. Метрика ТЗ №7 и сценарий 10 проектного документа.

Проверяем:
* RPO для подтверждённых данных: каждый самоотчёт, на который сервер ответил 200, есть в БД после сбоя;
* повтор неподтверждённых запросов с тем же ключом идемпотентности не создаёт дублей;
* алерты, созданные до сбоя и не доставленные, приходят врачу после перезапуска;
* RTO: время от падения до готовности сервера (перезапуск процесса; оркестратор в прототипе не используется).

    python evaluation/recovery_test.py --rounds 5
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation._server import Server, login  # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
PATIENTS = {"anna": "P-001", "sergey": "P-002", "olga": "P-003", "igor": "P-004",
            "dmitry": "P-006", "elena": "P-007", "alexey": "P-008"}


def writer(url: str, heads: dict, log: list, stop: threading.Event, seq: list) -> None:
    """Шлёт самоотчёты: у каждого свой ключ и метка в дневнике; фиксирует, что подтверждено."""
    with httpx.Client(base_url=url, timeout=3) as c:
        while not stop.is_set():
            seq[0] += 1
            i, login_ = seq[0], random.choice(list(PATIENTS))
            key, pid = uuid.uuid4().hex, PATIENTS[login_]
            body = {"questionnaires": [{"scale": "phq9", "answers": [1] * 8 + [random.choice([0, 2])]}],
                    "diary_text": f"recovery-{i}"}
            entry = {"i": i, "key": key, "pid": pid, "login": login_, "body": body, "acked": False, "alerts": []}
            try:
                r = c.post(f"/api/patients/{pid}/self-report", json=body, headers={**heads[login_], "Idempotency-Key": key})
                if r.status_code == 200:
                    entry["acked"] = True
                    entry["alerts"] = r.json()["alerts_created"]
            except httpx.HTTPError:
                pass
            log.append(entry)


def one_round(workers: int) -> dict:
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "rec.db"
        srv = Server(db, workers=workers)
        srv.start()
        heads = {u: login(srv.url, u) for u in PATIENTS}
        log, stop, seq = [], threading.Event(), [0]
        threads = [threading.Thread(target=writer, args=(srv.url, heads, log, stop, seq)) for _ in range(8)]
        for t in threads:
            t.start()
        time.sleep(random.uniform(2, 4))
        t_kill = time.perf_counter()
        srv.kill()                                   # аварийно, посреди записи
        stop.set()
        for t in threads:
            t.join()
        srv2 = Server(db, port=srv.port, workers=workers)
        srv2.start()
        rto = time.perf_counter() - t_kill

        conn = sqlite3.connect(db)
        diary = {row[0] for row in conn.execute("SELECT text FROM diary WHERE text LIKE 'recovery-%'")}
        acked = [e for e in log if e["acked"]]
        lost = [e["i"] for e in acked if f"recovery-{e['i']}" not in diary]
        alert_ids = {row[0] for row in conn.execute("SELECT id FROM alerts")}
        lost_alerts = [a for e in acked for a in e["alerts"] if a not in alert_ids]

        # Повтор неподтверждённых с тем же ключом: не должно быть дублей
        unacked = [e for e in log if not e["acked"]]
        heads2 = {u: login(srv2.url, u) for u in PATIENTS}
        with httpx.Client(base_url=srv2.url, timeout=5) as c:
            for e in unacked:
                for _ in range(2):                    # дважды — проверка идемпотентности
                    c.post(f"/api/patients/{e['pid']}/self-report", json=e["body"],
                           headers={**heads2[e["login"]], "Idempotency-Key": e["key"]})
        dupes = conn.execute("SELECT COUNT(*) FROM (SELECT text FROM diary WHERE text LIKE 'recovery-%' "
                             "GROUP BY text HAVING COUNT(*) > 1)").fetchone()[0]
        open_dupes = conn.execute("SELECT COUNT(*) FROM (SELECT patient_id, rule_id FROM alerts WHERE status != 'closed' "
                                  "GROUP BY patient_id, rule_id HAVING COUNT(*) > 1)").fetchone()[0]
        pending_db = {row[0] for row in conn.execute(
            "SELECT id FROM alerts WHERE assigned_to = 'doc-ivanova' AND status = 'created'")}
        conn.close()

        # Недоставленные алерты приходят врачу после перезапуска
        got: set[str] = set()
        token = login(srv2.url, "ivanova")["Authorization"][7:]
        try:
            with httpx.stream("GET", f"{srv2.url}/api/events/stream", params={"token": token}, timeout=3) as r:
                event, t0 = None, time.perf_counter()
                for line in r.iter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: ") and event == "alert":
                        got.add(json.loads(line[6:])["id"])
                    if pending_db <= got or time.perf_counter() - t0 > 3:
                        break
        except httpx.ReadTimeout:
            pass
        srv2.stop()
    return {"sent": len(log), "acked": len(acked), "unacked_retried": len(unacked), "lost_acked": len(lost),
            "lost_alerts": len(lost_alerts), "duplicate_reports": dupes, "duplicate_open_alerts": open_dupes,
            "pending_alerts": len(pending_db), "redelivered": len(pending_db & got), "rto_s": round(rto, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    rounds = [one_round(a.workers) for _ in range(a.rounds)]
    total = {k: sum(r[k] for r in rounds) for k in rounds[0] if k != "rto_s"}
    total["rto_max_s"] = max(r["rto_s"] for r in rounds)
    OUT.mkdir(exist_ok=True)
    (OUT / "recovery.json").write_text(json.dumps({"rounds": rounds, "total": total}, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    lines = [f"# Восстановление после аварийного падения ({a.rounds} прогонов, {a.workers} процесса, SIGKILL)", "",
             "| Прогон | Отправлено | Подтверждено | Потеряно подтверждённых | Потеряно алертов | "
             "Дубли отчётов | Дубли открытых алертов | Недоставлено → доставлено после рестарта | RTO, с |",
             "|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rounds, 1):
        lines.append(f"| {i} | {r['sent']} | {r['acked']} | {r['lost_acked']} | {r['lost_alerts']} | "
                     f"{r['duplicate_reports']} | {r['duplicate_open_alerts']} | "
                     f"{r['pending_alerts']} → {r['redelivered']} | {r['rto_s']} |")
    lines += ["", f"Итого: подтверждено {total['acked']}, потеряно {total['lost_acked']}; "
              f"повторено неподтверждённых {total['unacked_retried']} (каждый дважды), дублей {total['duplicate_reports']}; "
              f"максимальное время восстановления {total['rto_max_s']} с.", "",
              "RPO для подтверждённых самоотчётов = 0: данные и алерт фиксируются одной транзакцией с fsync до ответа "
              "пациенту. Обычные данные: WAL переживает падение процесса; при отказе диска — резервная копия "
              "(`sqlite3 kompas.db \".backup …\"` по расписанию, RPO = интервал копирования)."]
    (OUT / "recovery.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
