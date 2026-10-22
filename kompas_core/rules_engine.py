"""Движок правил с трёхзначной логикой (Клини): True / False / UNKNOWN.

Зачем трёхзначная логика: «нет данных» ≠ «нет признака». Если факт неизвестен,
условие даёт UNKNOWN, и правило может выдать отдельный результат on_unknown
(например, «недостаточно данных»), а не молча промолчать.

Правила лежат в YAML (rules/*.yaml) и добавляются без изменения кода.
Каждый вывод несёт id и версию правила, источник и факты-основания.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

RULES_DIR = Path(__file__).parent / "rules"


class _Unknown:
    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self):
        return "UNKNOWN"

    def __bool__(self):
        raise TypeError("UNKNOWN нельзя приводить к bool — обработайте явно")


UNKNOWN = _Unknown()

KINDS = {"alert", "routing", "therapy_warning", "review_task", "data_quality", "scope"}
PRIORITIES = {"emergency": 0, "urgent": 1, "planned": 2, "info": 3}
ROUTING = {"mandatory", "desirable", None}


def _cmp(op: str, a: Any, b: Any):
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if op == ">=":
        return a >= b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    if op == "<":
        return a < b
    if op == "in":
        return a in b
    if op == "not_in":
        return a not in b
    raise ValueError(f"Неизвестный оператор {op}")


def evaluate(cond: dict, facts: dict):
    """Возвращает True / False / UNKNOWN."""
    if "all" in cond:
        vals = [evaluate(c, facts) for c in cond["all"]]
        if any(v is False for v in vals):
            return False
        if any(v is UNKNOWN for v in vals):
            return UNKNOWN
        return True
    if "any" in cond:
        vals = [evaluate(c, facts) for c in cond["any"]]
        if any(v is True for v in vals):
            return True
        if any(v is UNKNOWN for v in vals):
            return UNKNOWN
        return False
    if "not" in cond:
        v = evaluate(cond["not"], facts)
        return UNKNOWN if v is UNKNOWN else (not v)

    fact, op = cond["fact"], cond["op"]
    if op == "is_unknown":
        return facts.get(fact) is None
    if op == "is_known":
        return facts.get(fact) is not None
    val = facts.get(fact)
    if val is None:
        return UNKNOWN
    return bool(_cmp(op, val, cond.get("value")))


@dataclass
class Finding:
    rule_id: str
    rule_version: str
    rule_status: str                 # draft | approved
    kind: str
    priority: str
    routing: Optional[str]
    title: str
    message: str
    patient_message: Optional[str]
    auto_actions: list[str]
    requires_doctor_confirmation: bool
    sources: list[str]
    evidence: dict
    fired_on: str                    # "true" | "unknown"

    def to_dict(self) -> dict:
        return asdict(self)


def _validate_rule(r: dict, path: Path) -> None:
    required = {"id", "version", "status", "title", "when", "output", "sources"}
    missing = required - r.keys()
    if missing:
        raise ValueError(f"{path.name}: правило {r.get('id')} без полей {missing}")
    if not r["sources"]:
        raise ValueError(f"{r['id']}: правило без источника недопустимо")
    for key in ("output", "on_unknown"):
        o = r.get(key)
        if o is None:
            continue
        if o["kind"] not in KINDS:
            raise ValueError(f"{r['id']}: неизвестный kind {o['kind']}")
        if o["priority"] not in PRIORITIES:
            raise ValueError(f"{r['id']}: неизвестный priority {o['priority']}")
        if o.get("routing") not in ROUTING:
            raise ValueError(f"{r['id']}: routing должен быть mandatory/desirable/null")


@lru_cache(maxsize=None)
def load_rules(rules_dir: str = str(RULES_DIR)) -> tuple:
    rules, seen = [], set()
    for path in sorted(Path(rules_dir).glob("*.yaml")):
        with path.open(encoding="utf-8") as f:
            for r in yaml.safe_load(f) or []:
                _validate_rule(r, path)
                if r["id"] in seen:
                    raise ValueError(f"Дублирующийся id правила {r['id']}")
                seen.add(r["id"])
                rules.append(r)
    return tuple(rules)


def _collect_facts(cond: dict, out: set) -> set:
    for k in ("all", "any"):
        for c in cond.get(k, []):
            _collect_facts(c, out)
    if "not" in cond:
        _collect_facts(cond["not"], out)
    if "fact" in cond:
        out.add(cond["fact"])
    return out


def _fmt(text: Optional[str], facts: dict) -> Optional[str]:
    """Подставляет {факт} в текст. Неизвестное значение показывается как «нет данных»."""
    if not text:
        return text
    import re
    return re.sub(r"\{([a-zA-Z0-9_.]+)\}",
                  lambda m: str(facts.get(m.group(1))) if facts.get(m.group(1)) is not None else "нет данных",
                  text)


def run_rules(facts: dict, rules: Optional[tuple] = None) -> list[Finding]:
    rules = rules if rules is not None else load_rules()
    findings: list[Finding] = []
    for r in rules:
        res = evaluate(r["when"], facts)
        if res is True:
            out, fired = r["output"], "true"
        elif res is UNKNOWN and r.get("on_unknown"):
            out, fired = r["on_unknown"], "unknown"
        else:
            continue
        used = sorted(_collect_facts(r["when"], set()))
        findings.append(Finding(
            rule_id=r["id"], rule_version=str(r["version"]), rule_status=r["status"],
            kind=out["kind"], priority=out["priority"], routing=out.get("routing"),
            title=r["title"], message=_fmt(out["message"].strip(), facts),
            patient_message=_fmt((out.get("patient_message") or "").strip(), facts) or None,
            auto_actions=list(out.get("auto_actions", [])),
            # Клинические действия — только после врача. Автодействия — только
            # информирование и уведомление (см. ALLOWED_AUTO_ACTIONS).
            requires_doctor_confirmation=True,
            sources=list(r["sources"]),
            evidence={k: facts.get(k) for k in used},
            fired_on=fired,
        ))
    findings.sort(key=lambda f: (PRIORITIES[f.priority], f.routing != "mandatory", f.rule_id))
    return findings


# Система сама делает только это. Назначение/отмена терапии и направление — нет.
ALLOWED_AUTO_ACTIONS = {
    "notify_doctor",
    "notify_deputy_on_timeout",
    "show_patient_emergency_instructions",
    "create_review_task",
    "request_repeat_questionnaire",
    "start_escalation_timer",
}


def check_auto_actions(rules: Optional[tuple] = None) -> None:
    for r in rules or load_rules():
        for key in ("output", "on_unknown"):
            o = r.get(key) or {}
            bad = set(o.get("auto_actions", [])) - ALLOWED_AUTO_ACTIONS
            if bad:
                raise ValueError(f"{r['id']}: запрещённые автодействия {bad}")
