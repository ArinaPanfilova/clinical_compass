"""Оболочка интерфейса: тема, раскладка рабочего места врача, телефон пациента, PWA, сдержанное движение."""
import json
import urllib.request

from playwright.sync_api import Browser, expect

from conftest import DEMO_BUTTONS


def _page(browser: Browser, server: str, login: str, **ctx):
    ctx.setdefault("viewport", {"width": 1440, "height": 900})
    c = browser.new_context(locale="ru-RU", **ctx)
    page = c.new_page()
    page.set_default_timeout(8000)
    page.goto(server)
    page.get_by_role("button", name=DEMO_BUTTONS[login]).click()
    return c, page


def _bg(page) -> str:
    return page.evaluate("getComputedStyle(document.body).backgroundColor")


def _wait_bg(page, color: str, same: bool) -> None:
    """Смена темы идёт плавно (~0,3 с): ждём, пока фон станет (или перестанет быть) нужным цветом."""
    op = "===" if same else "!=="
    page.wait_for_function(f"c => getComputedStyle(document.body).backgroundColor {op} c", arg=color, timeout=3000)


def test_theme_toggle_overrides_system_and_survives_reload(browser, server):
    c, page = _page(browser, server, "ivanova", color_scheme="light")
    expect(page.get_by_text("Мои пациенты")).to_be_visible()
    light = _bg(page)

    page.get_by_role("button", name="Тёмная тема").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    expect(page.get_by_role("button", name="Тёмная тема")).to_have_attribute("aria-pressed", "true")
    _wait_bg(page, light, same=False)

    page.reload()                                         # выбор хранится в localStorage
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")

    page.get_by_role("button", name="Тема как в системе").click()
    expect(page.locator("html")).not_to_have_attribute("data-theme", "dark")
    _wait_bg(page, light, same=True)
    c.close()


def test_light_choice_beats_dark_system_setting(browser, server):
    c, page = _page(browser, server, "anna", color_scheme="dark")
    expect(page.get_by_role("heading", name="Здравствуйте, Анна")).to_be_visible()
    dark = _bg(page)
    page.get_by_role("button", name="Светлая тема").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    _wait_bg(page, dark, same=False)
    c.close()


def test_doctor_workspace_fills_the_screen(browser, server):
    """1920×1080: список пациентов во всю высоту, карточка и правая колонка рядом, без пустой полосы справа."""
    c, page = _page(browser, server, "ivanova", viewport={"width": 1920, "height": 1080})
    expect(page.get_by_text("Мои пациенты")).to_be_visible()
    roster = page.get_by_role("navigation", name="Пациенты").bounding_box()
    card = page.locator("main.card").bounding_box()
    rail = page.get_by_role("complementary", name="Терапия, безопасность и сообщения").bounding_box()
    assert roster["y"] + roster["height"] >= 1078                       # до низа экрана
    assert card["x"] >= roster["x"] + roster["width"] - 1
    assert rail["x"] >= card["x"] + card["width"] - 1                    # колонка справа от карточки
    assert rail["x"] + rail["width"] >= 1918                             # и доходит до края
    assert rail["y"] + rail["height"] >= 1078
    c.close()


def test_safety_profile_is_compact_when_complete_and_clean(browser, server):
    c, page = _page(browser, server, "ivanova")
    page.get_by_role("button", name="Алексей Н.").click()
    profile = page.locator("section.panel").filter(has=page.get_by_role("heading", name="Профиль безопасности"))
    expect(profile).to_contain_text("12 из 12 · ограничений нет")
    expect(profile.locator("li").first).to_be_hidden()                  # факты свёрнуты
    profile.locator("summary").click()                                  # раскрыть все факты
    expect(profile.locator("li", has_text="Беременность")).to_contain_text("нет")
    c.close()


def test_patient_on_phone_is_fullscreen_without_device_frame(browser, server):
    c, page = _page(browser, server, "anna", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    expect(page.get_by_role("heading", name="Здравствуйте, Анна")).to_be_visible()
    app = page.get_by_label("Приложение пациента").bounding_box()
    bar = page.locator("header.topbar").bounding_box()
    assert bar["height"] <= 56                                           # верхняя панель в одну строку
    assert app["x"] == 0 and app["width"] == 390
    assert abs(app["y"] + app["height"] - 844) <= 1                      # до низа экрана
    expect(page.locator(".phone-status")).to_be_hidden()                 # нарисованная строка состояния не нужна
    expect(page.get_by_role("button", name="Мне сейчас очень плохо")).to_be_in_viewport()
    c.close()


def test_pwa_manifest_and_icons(browser, server):
    page = browser.new_page()
    page.goto(server)
    href = page.locator('link[rel="manifest"]').get_attribute("href")
    assert page.locator('link[rel="apple-touch-icon"]').count() == 1
    assert page.locator('meta[name="theme-color"]').count() == 1
    base = server + "/"
    m = json.loads(urllib.request.urlopen(base + href.lstrip("./")).read())
    assert m["display"] == "standalone" and m["theme_color"] and m["short_name"] == "Компас"
    sizes = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= sizes
    for i in m["icons"]:
        assert urllib.request.urlopen(base + i["src"]).status == 200
    page.close()


def test_reduced_motion_shows_final_numbers_at_once(browser, server):
    c, page = _page(browser, server, "researcher", reduced_motion="reduce")
    value = page.locator(".an-benefit-value")
    expect(value).to_contain_text("%")
    first = value.inner_text()
    page.wait_for_timeout(900)
    assert value.inner_text() == first                                   # без счёта: итог сразу
    c.close()


def test_kpi_numbers_count_up_without_reduced_motion(browser, server):
    c, page = _page(browser, server, "researcher")
    value = page.locator(".an-stats .stat-value").first
    expect(value).to_be_visible()
    seen = {value.inner_text() for _ in range(6) if not page.wait_for_timeout(60)}
    page.wait_for_timeout(900)
    final = value.inner_text()
    assert len(seen | {final}) > 1                                       # число набегает, а не появляется сразу
    c.close()
