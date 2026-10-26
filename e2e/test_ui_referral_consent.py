"""Направление к психиатру как действие врача; согласие пациента перед передачей данных."""
import re
import sqlite3

from playwright.sync_api import expect


def test_doctor_issues_referral_patient_sees_recommendation(open_as):
    doctor = open_as("ivanova")
    doctor.get_by_role("button", name=re.compile("Мария С.")).click()
    doctor.get_by_role("button", name="Направить к психиатру").click()
    expect(doctor.get_by_label("Основание направления")).not_to_be_empty()
    doctor.get_by_role("button", name="Оформить направление").click()
    expect(doctor.locator(".ref-item")).to_contain_text("Обязательно к психиатру")
    expect(doctor.locator(".ref-item")).to_contain_text("оформлено")
    expect(doctor.locator(".log")).to_contain_text("Направление к психиатру")

    patient = open_as("maria")
    expect(patient.get_by_role("note")).to_contain_text("Врач рекомендовал консультацию психиатра")


def test_consent_screen_before_first_data(open_as, tmp_path):
    db = sqlite3.connect(tmp_path / "e2e.db")
    db.execute("DELETE FROM consents WHERE patient_id = 'P-001'")
    db.commit()
    db.close()
    page = open_as("anna")
    expect(page.get_by_role("heading", name="Согласие на обработку данных о здоровье")).to_be_visible()
    expect(page.get_by_role("button", name="Принимаю")).to_be_disabled()
    expect(page.get_by_role("button", name="Мне сейчас очень плохо")).to_be_enabled()   # экстренное — всегда
    page.get_by_label(re.compile("Я прочитал")).check()
    page.get_by_role("button", name="Принимаю").click()
    expect(page.get_by_role("heading", name="Здравствуйте, Анна")).to_be_visible()


def test_therapy_options_by_guideline_show_aviandr_line(open_as):
    doctor = open_as("ivanova")
    doctor.get_by_role("button", name=re.compile("Анна К.")).click()
    panel = doctor.locator("section.panel").filter(has=doctor.get_by_role("heading", name="Варианты терапии"))
    expect(panel).to_contain_text("Генерализованное тревожное расстройство")
    expect(panel).to_contain_text("СИОЗС")
    drug = doctor.locator("section.panel").filter(has=doctor.get_by_role("heading", name="Авиандр", exact=True))
    expect(drug).to_contain_text("третья линия")
