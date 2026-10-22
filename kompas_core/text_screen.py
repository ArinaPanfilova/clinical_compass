"""Вспомогательный поиск тревожных формулировок в свободном тексте дневника.

Это НЕ классификатор риска. Назначение — поднять запись наверх для врача.
Словарь заведомо неполный: чувствительность измеряется на синтетике и честно
указывается в отчёте. Все записи доступны врачу целиком независимо от флага.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# (шаблон, комментарий). Словарь утверждает клинический лид.
PATTERNS = [
    r"не\s+хоч(у|ется)\s+(больше\s+)?жить",
    r"хоч(у|ется)\s+умереть",
    r"поконч(ить|у)\s+с\s+собой",
    r"лучше\s+бы\s+меня\s+не\s+было",
    r"(причинить|навредить)\s+себе",
    r"(порезать|резать)\s+себя",
    r"нет\s+смысла\s+жить",
    r"суицид\w*",
    r"наглотаться\s+таблеток",
    r"(уйти|исчезнуть)\s+навсегда",
    r"не\s+вижу\s+выхода",
]

# Отрицание рядом с совпадением («мыслей о суициде нет», «никогда не думала причинить себе вред»)
NEGATION_BEFORE = re.compile(r"(нет\s+мыслей|никогда\s+не|не\s+думаю|не\s+было\s+мыслей|без\s+мыслей)[^.!?]{0,40}$")
NEGATION_AFTER = re.compile(r"^[^.!?]{0,15}\b(нет|не\s+было|отсутствуют)\b")

_compiled = [re.compile(p, re.IGNORECASE) for p in PATTERNS]


@dataclass
class TextScreenResult:
    flagged: bool
    matched: list[str]
    negated: list[str]


def screen_text(text: str) -> TextScreenResult:
    t = (text or "").lower().replace("ё", "е")
    matched, negated = [], []
    for rx in _compiled:
        for m in rx.finditer(t):
            before, after = t[:m.start()], t[m.end():]
            if NEGATION_BEFORE.search(before) or NEGATION_AFTER.search(after):
                negated.append(m.group(0))
            else:
                matched.append(m.group(0))
    return TextScreenResult(bool(matched), matched, negated)
