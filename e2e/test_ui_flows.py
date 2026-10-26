"""Типовые сценарии ТЗ через настоящий интерфейс: роли, самоотчёт → алерт → решение, сообщения, приём."""
import re

from playwright.sync_api import Page, expect

from conftest import ESCALATE_AFTER_S

OPT = ["Ни разу", "Несколько дней", "Более половины дней", "Почти каждый день"]


def fill_questionnaire(page: Page, item9: int) -> None:
    page.get_by_role("button", name="Заполнить анкету").click()
    for i in range(16):
        page.get_by_role("radio", name=OPT[item9 if i == 8 else 1]).click()
        if i < 15:
            expect(page.get_by_text(f"Вопрос {i + 2} из 16")).to_be_visible()
    page.get_by_role("button", name="Готово").click()


def test_login_screen_and_patient_lands_in_own_app(open_as):
    page = open_as("anna")
    expect(page.get_by_role("heading", name="Здравствуйте, Анна")).to_be_visible()
    expect(page.get_by_role("button", name="Мне сейчас очень плохо")).to_be_visible()
    expect(page.get_by_text("Мои пациенты")).to_have_count(0)


def test_researcher_sees_only_anonymized_analytics(open_as):
    page = open_as("researcher")
    expect(page.get_by_role("heading", name="Авиандр: наблюдение применения")).to_be_visible()
    expect(page.get_by_text("Мои пациенты")).to_have_count(0)
    expect(page.get_by_text("Анна К.")).to_have_count(0)


def test_doctor_has_patients_and_analytics_tabs(open_as):
    page = open_as("ivanova")
    expect(page.get_by_text("Мои пациенты")).to_be_visible()
    page.get_by_role("button", name="Наблюдение препарата", exact=True).click()
    expect(page.get_by_role("heading", name="Авиандр: наблюдение применения")).to_be_visible()
    expect(page.get_by_text("Индекс устойчивой пользы").first).to_be_visible()


def test_item9_answer_reaches_doctor_live_then_accept_and_confirm(open_as):
    doctor = open_as("ivanova")
    expect(doctor.get_by_text("Мои пациенты")).to_be_visible()
    patient = open_as("anna")
    fill_questionnaire(patient, item9=2)
    patient.get_by_role("button", name="Отправить врачу").click()
    expect(patient.get_by_role("status")).to_contain_text("Врач свяжется")

    toast = doctor.get_by_role("alert").filter(has_text="Анна К.")
    expect(toast).to_contain_text("Срочно", timeout=5000)
    toast.click()
    card = doctor.get_by_role("article", name="PHQ-9, п.9: мысли о смерти/самоповреждении больше")
    card.get_by_role("button", name="Принять в работу").click()
    expect(card.locator(".lifecycle li.done", has_text="принят врачом")).to_be_visible()
    card.get_by_role("button", name="Подтвердить").click()
    expect(card.get_by_text("Подтверждено врачом")).to_be_visible()

    doctor.reload()
    doctor.get_by_role("button", name=re.compile("Анна К.")).click()
    card = doctor.get_by_role("article", name="PHQ-9, п.9: мысли о смерти/самоповреждении больше")
    expect(card.get_by_text("Подтверждено врачом")).to_be_visible()        # решение хранится на сервере


def test_messages_roundtrip(open_as):
    patient = open_as("anna")
    patient.get_by_role("button", name="Сообщения").click()
    patient.get_by_label("Вопрос врачу").fill("Можно перенести приём на пятницу?")
    patient.get_by_role("button", name="Отправить сообщение").click()
    expect(patient.get_by_text("Можно перенести приём на пятницу?")).to_be_visible()

    doctor = open_as("ivanova")
    doctor.get_by_role("button", name=re.compile("Анна К.")).click()
    expect(doctor.get_by_text("Можно перенести приём на пятницу?")).to_be_visible()
    doctor.get_by_label("Ответ пациенту").fill("Да, жду вас в пятницу в 10:00")
    doctor.get_by_role("button", name="Отправить", exact=True).click()

    patient.reload()
    patient.get_by_role("button", name="Сообщения").click()
    expect(patient.get_by_text("Да, жду вас в пятницу в 10:00")).to_be_visible()


def test_intake_mark_updates_doctor_card(open_as):
    patient = open_as("alexey")
    patient.get_by_role("button", name="Пропустил(а)").click()
    expect(patient.get_by_text("Отметка сохранена")).to_be_visible()
    doctor = open_as("ivanova")
    doctor.get_by_role("button", name=re.compile("Алексей Н.")).click()
    expect(doctor.locator(".adh")).to_contain_text("пропустил")


def test_unaccepted_alert_escalates_to_deputy(open_as):
    patient = open_as("anna")
    patient.get_by_role("button", name="Мне сейчас очень плохо").click()
    expect(patient.get_by_role("dialog")).to_contain_text("112")
    deputy = open_as("petrov")
    toast = deputy.get_by_role("alert").filter(has_text="Анна К.")
    expect(toast).to_contain_text("Экстренно", timeout=(ESCALATE_AFTER_S + 6) * 1000)
    expect(deputy.get_by_text("замещение").first).to_be_visible()


def test_logout_returns_to_login(open_as):
    page = open_as("ivanova")
    page.get_by_role("button", name="Выйти").click()
    expect(page.get_by_role("heading", name="Вход в Компас")).to_be_visible()


DOC = ("Выписка. Дата: 20.10.2026. Ds: F41.1 Генерализованное тревожное расстройство. Сопут.: ГБ II ст. "
       "Эпилепсию отрицает. Беременность исключена, не кормит грудью. СКФ 85 мл/мин. Печёночной "
       "недостаточности нет. Аллергию отрицает. Ингибиторы МАО не принимал. Терапия: сертралин 50 мг утром.")


def test_document_extraction_then_profile_completion_changes_drug_status(open_as):
    doctor = open_as("ivanova")
    doctor.get_by_role("button", name=re.compile("Игорь В.")).click()
    drug = doctor.locator("section.panel").filter(has=doctor.get_by_role("heading", name="Авиандр", exact=True))
    expect(drug).to_contain_text("Недостаточно данных")

    doctor.get_by_role("button", name="Загрузить документ").click()
    doctor.get_by_label("Текст документа").fill(DOC)
    doctor.get_by_role("button", name="Извлечь сведения").click()
    dialog = doctor.get_by_role("dialog")
    expect(dialog).to_contain_text("Эпилепсию отрицает")
    expect(dialog).to_contain_text("извлечено, не проверено")
    dialog.get_by_role("button", name="Подтвердить выбранное").click()
    expect(dialog).to_have_count(0)

    profile = doctor.locator("section.panel").filter(has=doctor.get_by_role("heading", name="Профиль безопасности"))
    expect(profile.locator("li", has_text="Эпилепсия")).to_contain_text("нет")
    for _ in range(12):                                  # дозаполнить со слов пациента
        no = profile.get_by_role("button", name=re.compile(": нет$"))
        if no.count() == 0:
            break
        left = no.count()
        no.first.click()
        expect(no).to_have_count(left - 1)
    expect(drug).to_contain_text("Можно рассмотреть")
    expect(doctor.locator(".log")).to_contain_text("Профиль безопасности")
