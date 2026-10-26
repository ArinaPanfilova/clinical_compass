"""Замечания пользователя к интерфейсу: обратная связь, пересмотр решений, сокращения, графики, движение."""
import re

from playwright.sync_api import expect

from conftest import DEMO_BUTTONS

NYA = re.compile(r"(?<![А-ЯЁа-яё])НЯ(?![А-ЯЁа-яё])")      # «НЯ» отдельным словом


def login(browser, server, who, **ctx):
    ctx.setdefault("viewport", {"width": 1440, "height": 900})
    c = browser.new_context(locale="ru-RU", **ctx)
    page = c.new_page()
    page.set_default_timeout(8000)
    page.goto(server)
    page.get_by_role("button", name=DEMO_BUTTONS[who]).click()
    expect(page.get_by_role("heading", name="Вход в Компас")).to_have_count(0)
    return c, page


def test_no_connection_badge_while_everything_works(browser, server):
    c, page = login(browser, server, "ivanova")
    expect(page.get_by_text("Мои пациенты")).to_be_visible()
    expect(page.get_by_text("Сервер подключён")).to_have_count(0)
    c.close()


def test_abbreviation_nya_is_not_used_bare(browser, server):
    c, page = login(browser, server, "ivanova")
    page.get_by_role("button", name=re.compile("Дмитрий Л.")).click()
    expect(page.get_by_role("heading", name="Нежелательные явления").first).to_be_visible()
    assert not NYA.search(page.inner_text("body"))
    page.get_by_role("button", name="Наблюдение препарата").click()
    expect(page.get_by_text("Индекс устойчивой пользы").first).to_be_visible()
    assert not NYA.search(page.inner_text("body"))
    c.close()


def test_decision_can_be_revised_and_both_stay_in_journal(browser, server):
    c, page = login(browser, server, "ivanova")
    page.get_by_role("button", name=re.compile("Мария С.")).click()
    card = page.get_by_role("article", name="PHQ-9 в диапазоне тяжёлой выраженности (≥20)")
    card.get_by_role("button", name="Подтвердить").click()
    expect(card.get_by_text("Подтверждено врачом")).to_be_visible()
    card.get_by_role("button", name="Пересмотреть").click()
    card.get_by_role("button", name="Отклонить").click()
    card.get_by_role("textbox").fill("пациентка уже наблюдается у психиатра")
    card.get_by_role("button", name="Отклонить").click()
    expect(card.get_by_text("Отклонено врачом")).to_be_visible()
    log = page.locator(".log")
    expect(log).to_contain_text("Подтверждено")
    expect(log).to_contain_text("Отклонено")
    c.close()


def test_dynamics_shows_both_scales_at_once(browser, server):
    c, page = login(browser, server, "ivanova")
    page.get_by_role("button", name=re.compile("Мария С.")).click()
    expect(page.get_by_role("figure", name="Динамика PHQ-9")).to_be_visible()
    expect(page.get_by_role("figure", name="Динамика GAD-7")).to_be_visible()
    c.close()


def test_phone_confirmation_appears_where_the_patient_looks(browser, server):
    """Длинный экран (пациент на терапии): кнопка «Отправить врачу» ниже первого экрана."""
    c, page = login(browser, server, "alexey", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    page.get_by_label("Напишите своими словами").fill("Сегодня спокойнее, спал лучше")
    send = page.get_by_role("button", name="Отправить врачу")
    send.scroll_into_view_if_needed()
    send.click()
    expect(page.get_by_role("status")).to_be_in_viewport()
    expect(page.get_by_role("status")).to_contain_text("Отправлено")
    c.close()


def test_reduced_motion_keeps_gentle_fades(browser, server):
    """«Уменьшить движение» убирает сдвиги и пульсацию, но не все переходы: плавное появление остаётся."""
    c, page = login(browser, server, "ivanova", reduced_motion="reduce")
    card = page.locator("main.card").first
    expect(card).to_be_visible()
    assert card.evaluate("e => getComputedStyle(e).animationName") == "fade-in"
    c.close()
    c, page = login(browser, server, "ivanova")
    assert page.locator("main.card").first.evaluate("e => getComputedStyle(e).animationName") == "view-in"
    c.close()
