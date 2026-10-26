"""Эргономика (метрика ТЗ №4): число действий пользователя и время отклика интерфейса в типовых сценариях.

Сценарии проходит скрипт (Playwright) на настоящем сервере и собранном интерфейсе. Действие — клик или ввод.
Отклик — время от действия до появления ожидаемого результата на экране. Время человека на задачу
скрипт не измеряет: для этого нужны формативные тесты с 5–8 врачами (план апробации).

    python evaluation/ergonomics.py --runs 5
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import Locator, Page, expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation._server import Server, pct  # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
PHQ = ["Совсем нет", "В течение нескольких дней", "Более, чем половину этого времени", "Почти каждый день"]
GAD = ["Совсем нет", "В течение нескольких дней", "Более чем половину этого времени", "Почти каждый день"]
DOC = ("Выписка. Дата: 20.10.2026. Ds: F41.1 Генерализованное тревожное расстройство. Сопут.: ГБ II ст. "
       "Эпилепсию отрицает. Беременность исключена, не кормит грудью. СКФ 85 мл/мин. Печёночной "
       "недостаточности нет. Аллергию отрицает. Ингибиторы МАО не принимал. Терапия: сертралин 50 мг утром.")


class Meter:
    """Считает действия и время отклика: действие → ожидаемый элемент на экране."""

    def __init__(self) -> None:
        self.actions, self.latency_ms, self.t0 = 0, [], time.perf_counter()

    def act(self, do, then: Locator | None = None) -> None:
        t = time.perf_counter()
        do()
        if then is not None:
            expect(then).to_be_visible()
        self.actions += 1
        self.latency_ms.append((time.perf_counter() - t) * 1000)

    def result(self) -> dict:
        return {"actions": self.actions, "total_s": round(time.perf_counter() - self.t0, 2),
                "latency_p50_ms": round(pct(self.latency_ms, 50)), "latency_max_ms": round(max(self.latency_ms))}


def login(browser, url: str, who: str) -> Page:
    page = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU").new_page()
    page.set_default_timeout(10000)
    page.goto(url)
    page.get_by_role("button", name=who).click()
    expect(page.get_by_role("heading", name="Вход в Компас")).to_have_count(0)
    return page


def patient_questionnaire(browser, url) -> dict:
    p = login(browser, url, "Анна К.")
    expect(p.get_by_role("heading", name="Здравствуйте, Анна")).to_be_visible()
    m = Meter()
    m.act(lambda: p.get_by_role("button", name="Заполнить анкету").click(), p.get_by_text("Вопрос 1 из 16"))
    for i in range(16):
        opts = PHQ if i < 9 else GAD
        nxt = p.get_by_text(f"Вопрос {i + 2} из 16") if i < 15 else p.get_by_role("button", name="Готово")
        m.act(lambda: p.get_by_role("radio", name=opts[1], exact=True).click(), nxt)
    m.act(lambda: p.get_by_role("button", name="Готово").click(), p.get_by_role("button", name="Отправить врачу"))
    m.act(lambda: p.get_by_role("button", name="Отправить врачу").click(), p.get_by_role("status"))
    return m.result()


def doctor_handles_alert(browser, url) -> dict:
    d = login(browser, url, "Иванова Е. А.")
    expect(d.get_by_text("Мои пациенты")).to_be_visible()
    p = login(browser, url, "Анна К.")
    t = time.perf_counter()
    p.get_by_role("button", name="Мне сейчас очень плохо").click()
    toast = d.get_by_role("alert").filter(has_text="Анна К.")
    expect(toast).to_be_visible()
    delivery_ms = (time.perf_counter() - t) * 1000
    m = Meter()
    card = d.get_by_role("article", name="Пациент сообщил о непосредственной опасности")
    m.act(lambda: toast.click(), card)
    m.act(lambda: card.get_by_role("button", name="Принять в работу").click(),
          card.locator(".lifecycle li.done", has_text="принят врачом"))
    m.act(lambda: card.get_by_role("button", name="Подтвердить").click(), card.get_by_text("Подтверждено врачом"))
    return {**m.result(), "alert_on_screen_ms": round(delivery_ms)}


def doctor_referral(browser, url) -> dict:
    d = login(browser, url, "Иванова Е. А.")
    m = Meter()
    m.act(lambda: d.get_by_role("button", name=re.compile("Мария С.")).click(), d.get_by_role("button", name="Направить к психиатру"))
    m.act(lambda: d.get_by_role("button", name="Направить к психиатру").click(), d.get_by_role("button", name="Оформить направление"))
    m.act(lambda: d.get_by_role("button", name="Оформить направление").click(), d.locator(".ref-item"))
    return m.result()


def doctor_document(browser, url) -> dict:
    d = login(browser, url, "Иванова Е. А.")
    m = Meter()
    m.act(lambda: d.get_by_role("button", name=re.compile("Игорь В.")).click(), d.get_by_role("button", name="Загрузить документ"))
    m.act(lambda: d.get_by_role("button", name="Загрузить документ").click(), d.get_by_label("Текст документа"))
    m.act(lambda: d.get_by_label("Текст документа").fill(DOC), None)
    m.act(lambda: d.get_by_role("button", name="Извлечь сведения").click(), d.get_by_role("button", name="Подтвердить выбранное"))
    m.act(lambda: d.get_by_role("button", name="Подтвердить выбранное").click(), None)
    expect(d.get_by_role("dialog")).to_have_count(0)
    no = d.get_by_role("button", name=re.compile(": нет$"))
    while no.count():
        left = no.count()
        m.act(lambda: no.first.click(), None)
        expect(no).to_have_count(left - 1)
    expect(d.get_by_text("Можно рассмотреть").first).to_be_visible()
    return m.result()


def patient_message_and_intake(browser, url) -> dict:
    p = login(browser, url, "Алексей Н.")
    m = Meter()
    m.act(lambda: p.get_by_role("button", name="Принял(а)").click(), p.get_by_text("Отметка сохранена"))
    m.act(lambda: p.get_by_role("button", name="Сообщения").click(), p.get_by_label("Вопрос врачу"))
    m.act(lambda: p.get_by_label("Вопрос врачу").fill("Можно принимать после еды?"), None)
    m.act(lambda: p.get_by_role("button", name="Отправить сообщение").click(), p.get_by_text("Можно принимать после еды?"))
    return m.result()


SCENARIOS = [
    ("Пациент: заполнить PHQ-9 + GAD-7 и отправить", patient_questionnaire),
    ("Врач: экстренный сигнал → принять → подтвердить", doctor_handles_alert),
    ("Врач: направить к психиатру", doctor_referral),
    ("Врач: выписка → профиль → статус Авиандра", doctor_document),
    ("Пациент: отметить приём и написать врачу", patient_message_and_intake),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    a = ap.parse_args()
    rows = {name: [] for name, _ in SCENARIOS}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for _ in range(a.runs):
            for name, fn in SCENARIOS:
                with tempfile.TemporaryDirectory() as d:        # чистые данные на каждый прогон
                    srv = Server(Path(d) / "erg.db", workers=2)
                    srv.start()
                    try:
                        rows[name].append(fn(browser, srv.url))
                    finally:
                        srv.stop()
        browser.close()
    summary = []
    for name, rs in rows.items():
        s = {"scenario": name, "runs": len(rs), "actions": rs[0]["actions"],
             "total_s_median": round(statistics.median(r["total_s"] for r in rs), 2),
             "latency_p50_ms": round(statistics.median(r["latency_p50_ms"] for r in rs)),
             "latency_max_ms": max(r["latency_max_ms"] for r in rs)}
        if "alert_on_screen_ms" in rs[0]:
            s["alert_on_screen_ms_median"] = round(statistics.median(r["alert_on_screen_ms"] for r in rs))
        summary.append(s)
    OUT.mkdir(exist_ok=True)
    (OUT / "ergonomics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# Эргономика типовых сценариев ({a.runs} прогонов, скрипт в браузере)", "",
             "Действие — клик или ввод текста. Отклик — от действия до появления результата на экране.",
             "Время человека на задачу скрипт не измеряет: это формативные тесты с врачами (план апробации).", "",
             "| Сценарий | Действий | Время скрипта, с (медиана) | Отклик p50, мс | Отклик max, мс |",
             "|---|---|---|---|---|"]
    for s in summary:
        lines.append(f"| {s['scenario']} | {s['actions']} | {s['total_s_median']} | {s['latency_p50_ms']} | {s['latency_max_ms']} |")
    alert = next(s for s in summary if "alert_on_screen_ms_median" in s)
    lines += ["", f"Экстренная кнопка пациента → сигнал на экране врача: {alert['alert_on_screen_ms_median']} мс (медиана)."]
    (OUT / "ergonomics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
