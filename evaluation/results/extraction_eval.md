# Извлечение ключевых сведений из медицинских документов

Приёмочный набор: пул `test`, n=300, seed=2026 — перефразировки, которых нет в пуле разработки. Для сравнения: пул `dev`, n=300, seed=42 (на нём извлекатель разрабатывался).

> Синтетические документы: проверка реализации на заданной модели вариативности текста, **не** оценка на реальных выписках. Пул `test` написан отдельным исполнителем до извлекателя; извлекатель по ошибкам на `test` не настраивался.

## Группы сущностей

| Группа | test P | test R | test F1 | TP/FP/FN (test) | dev F1 |
|---|---|---|---|---|---|
| Диагнозы (код + статус) | 0.801 | 0.820 | **0.811** | 601/149/132 | 1.000 |
| Препараты (МНН + статус) | 0.979 | 0.947 | **0.962** | 638/14/36 | 1.000 |
| Дозы (МНН + доза) | 1.000 | 0.943 | **0.971** | 595/0/36 | 1.000 |
| Аллергии (аллерген) | 1.000 | 0.455 | **0.625** | 65/0/78 | 1.000 |
| Статус аллергий (нет сведений / отрицает / есть), точность | | | **0.727** | | 1.000 |

## Факты безопасности (три значения: True / False / None)

| Факт | test macro-F1 | F1 True | F1 False | F1 None | точность | dev macro-F1 |
|---|---|---|---|---|---|---|
| `epilepsy_or_organic_brain_lesion` (противопоказание) | **0.855** | 0.729 | 0.862 | 0.974 | 0.893 | 1.000 |
| `pregnancy` (противопоказание) | **0.840** | 0.857 | 0.702 | 0.961 | 0.930 | 1.000 |
| `breastfeeding` (противопоказание) | **0.919** | 0.769 | 1.000 | 0.988 | 0.980 | 1.000 |
| `renal_gfr_below_60` (противопоказание) | **0.907** | 0.875 | 0.920 | 0.925 | 0.917 | 1.000 |
| `hepatic_insufficiency` (противопоказание) | **0.864** | 0.948 | 0.765 | 0.878 | 0.863 | 1.000 |
| `maoi_within_2_weeks` (противопоказание) | **0.938** | 0.915 | 0.938 | 0.961 | 0.950 | 1.000 |
| `cardiovascular_disease` | **0.843** | 0.823 | 0.753 | 0.952 | 0.877 | 1.000 |
| `endocrine_disorder` | **0.820** | 0.853 | 0.672 | 0.934 | 0.857 | 1.000 |
| `substance_dependence` | **0.826** | 0.696 | 0.822 | 0.960 | 0.863 | 1.000 |
| `lactose_intolerance` | **0.722** | 0.936 | 0.438 | 0.794 | 0.740 | 1.000 |
| `hypersensitivity_aviandr` (противопоказание) | **0.766** | 0.606 | 0.754 | 0.940 | 0.900 | 1.000 |

## Опасные ошибки по противопоказаниям Авиандра — test

Эталон True, извлечено False или None: **50** из 245 положительных (False при True — **0**, None при True — 50).
Доля пропусков 0.204, 95% ДИ Уилсона [0.158; 0.259].

| Противопоказание | положительных | False при True | None при True |
|---|---|---|---|
| `hypersensitivity_aviandr` | 23 | 0 | 13 |
| `epilepsy_or_organic_brain_lesion` | 51 | 0 | 8 |
| `maoi_within_2_weeks` | 32 | 0 | 5 |
| `renal_gfr_below_60` | 45 | 0 | 10 |
| `hepatic_insufficiency` | 61 | 0 | 6 |
| `pregnancy` | 17 | 0 | 2 |
| `breastfeeding` | 16 | 0 | 6 |

Предостережения (не противопоказания), пропуски при эталоне True: `cardiovascular_disease` — False 0, None 1, `endocrine_disorder` — False 0, None 0, `substance_dependence` — False 0, None 12, `lactose_intolerance` — False 0, None 6

Примеры:

- test-2026-0001 [Б] `renal_gfr_below_60` → None
- test-2026-0002 [Б] `hypersensitivity_aviandr` → None
- test-2026-0006 [А] `hypersensitivity_aviandr` → None
- test-2026-0018 [В] `hepatic_insufficiency` → None
- test-2026-0021 [Б] `renal_gfr_below_60` → None
- test-2026-0029 [Б] `epilepsy_or_organic_brain_lesion` → None
- test-2026-0030 [Б] `maoi_within_2_weeks` → None
- test-2026-0046 [Б] `hypersensitivity_aviandr` → None
- test-2026-0058 [В] `hepatic_insufficiency` → None
- test-2026-0063 [А] `renal_gfr_below_60` → None

## Опасные ошибки по противопоказаниям Авиандра — dev

Эталон True, извлечено False или None: **0** из 260 положительных (False при True — **0**, None при True — 0).
0 ошибок; верхняя граница доли пропусков по правилу трёх ≈ 0.012.

| Противопоказание | положительных | False при True | None при True |
|---|---|---|---|
| `hypersensitivity_aviandr` | 25 | 0 | 0 |
| `epilepsy_or_organic_brain_lesion` | 57 | 0 | 0 |
| `maoi_within_2_weeks` | 38 | 0 | 0 |
| `renal_gfr_below_60` | 54 | 0 | 0 |
| `hepatic_insufficiency` | 46 | 0 | 0 |
| `pregnancy` | 24 | 0 | 0 |
| `breastfeeding` | 16 | 0 | 0 |

Предостережения (не противопоказания), пропуски при эталоне True: `cardiovascular_disease` — False 0, None 0, `endocrine_disorder` — False 0, None 0, `substance_dependence` — False 0, None 0, `lactose_intolerance` — False 0, None 0

## По шаблонам (test)

А — выписка с разделами, Б — осмотр сплошным текстом, В — краткое направление с сокращениями.

| Шаблон | документов | F1 диагнозы | F1 препараты | F1 дозы | F1 аллергии | мин. macro-F1 по фактам | опасных ошибок (из них False) |
|---|---|---|---|---|---|---|---|
| А | 106 | 0.779 | 0.968 | 0.976 | 0.529 | 0.744 (`hypersensitivity_aviandr`) | 15 (0) |
| Б | 86 | 0.887 | 0.959 | 0.970 | 0.710 | 0.735 (`substance_dependence`) | 17 (0) |
| В | 108 | 0.781 | 0.959 | 0.966 | 0.641 | 0.496 (`lactose_intolerance`) | 18 (0) |

## Частые ошибки на test

- `allergies`: пропуск авиандр ×16; пропуск цефтриаксон ×13; пропуск пенициллин ×12; пропуск амоксициллин ×9; пропуск прокаин ×7
- `breastfeeding`: эталон True → None ×6
- `cardiovascular_disease`: эталон False → True ×21; эталон False → None ×15; эталон True → None ×1
- `diagnoses`: лишнее ('E14.9', 'confirmed') ×43; лишнее ('I10', 'confirmed') ×24; лишнее ('I25.9', 'confirmed') ×21; лишнее ('K72.9', 'confirmed') ×14; пропуск ('K72.1', 'confirmed') ×12
- `doses`: пропуск ('дулоксетин', 60.0) ×9; пропуск ('миртазапин', 15.0) ×8; пропуск ('миртазапин', 30.0) ×8; пропуск ('бромдигидрохлорфенилбензодиазепин', 1.0) ×5; пропуск ('кетоконазол', 200.0) ×2
- `endocrine_disorder`: эталон False → True ×22; эталон False → None ×21
- `epilepsy_or_organic_brain_lesion`: эталон False → True ×24; эталон True → None ×8
- `hepatic_insufficiency`: эталон False → None ×35; эталон True → None ×6
- `hypersensitivity_aviandr`: эталон False → None ×17; эталон True → None ×13
- `lactose_intolerance`: эталон False → None ×72; эталон True → None ×6
- `maoi_within_2_weeks`: эталон False → None ×10; эталон True → None ×5
- `medications`: лишнее ('авиандр', 'current') ×14; пропуск ('миртазапин', 'current') ×12; пропуск ('дулоксетин', 'current') ×7; пропуск ('бромдигидрохлорфенилбензодиазепин', 'current') ×7; пропуск ('миртазапин', 'cancelled') ×4
- `pregnancy`: эталон False → None ×16; эталон None → True ×2; эталон True → None ×2; эталон False → True ×1
- `renal_gfr_below_60`: эталон False → None ×15; эталон True → None ×10
- `substance_dependence`: эталон False → True ×29; эталон True → None ×12

## test против dev

На `test` хуже, чем на `dev`: `diagnoses`, `medications`, `doses`, `allergies`, `epilepsy_or_organic_brain_lesion`, `pregnancy`, `breastfeeding`, `renal_gfr_below_60`, `hepatic_insufficiency`, `maoi_within_2_weeks`, `cardiovascular_disease`, `endocrine_disorder`, `substance_dependence`, `lactose_intolerance`, `hypersensitivity_aviandr`. Это цена перефразировок, которых не было при разработке; извлекатель под них не подгонялся.

Время извлечения на документ: p50 = 1.99 мс, p95 = 3.11 мс.
