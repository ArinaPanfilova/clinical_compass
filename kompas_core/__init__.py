"""Компас — ядро клинической логики (шкалы, динамика, правила, проверки препаратов,
извлечение сведений из медицинских документов)."""
from .pipeline import evaluate_patient, build_facts, ENGINE_VERSION
from .scales import score, load_passport, available_scales
from .dynamics import classify_change, reliable_change_threshold, trend
from .rules_engine import run_rules, load_rules, check_auto_actions
from .drugs import check_drug, load_card
from .text_screen import screen_text
from .analytics import aviandr_report
from .extraction import extract

__all__ = [
    "evaluate_patient", "build_facts", "ENGINE_VERSION",
    "score", "load_passport", "available_scales",
    "classify_change", "reliable_change_threshold", "trend",
    "run_rules", "load_rules", "check_auto_actions",
    "check_drug", "load_card", "screen_text",
    "aviandr_report", "extract",
]
