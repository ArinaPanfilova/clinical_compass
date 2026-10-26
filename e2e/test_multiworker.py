"""Масштабирование: два процесса сервера на одной БД. Алерт, созданный в одном процессе,
доходит до врача, подключённого к другому (доставка из БД, а не только из памяти процесса)."""
import json
import threading
import time

import httpx

from evaluation._server import Server, login


def test_alert_created_in_one_process_reaches_doctor_on_another(tmp_path):
    a = Server(tmp_path / "shared.db")
    a.start()
    b = Server(tmp_path / "shared.db")
    b.start()
    try:
        token = login(b.url, "ivanova")["Authorization"][7:]
        got: list[dict] = []

        def listen():
            with httpx.stream("GET", f"{b.url}/api/events/stream", params={"token": token}, timeout=15) as r:
                event = None
                for line in r.iter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: ") and event == "alert":
                        got.append(json.loads(line[6:]))
                        return

        t = threading.Thread(target=listen, daemon=True)
        t.start()
        time.sleep(1)
        body = {"questionnaires": [{"scale": "phq9", "answers": [1] * 8 + [2]}]}
        r = httpx.post(f"{a.url}/api/patients/P-001/self-report", json=body, headers=login(a.url, "anna"))
        assert r.status_code == 200
        sent = time.perf_counter()
        t.join(5)
        assert got, "алерт не дошёл до врача на другом процессе"
        assert got[0]["patient_id"] == "P-001" and got[0]["rule_id"] == "SAFE-002"
        assert time.perf_counter() - sent < 3
    finally:
        a.stop()
        b.stop()
