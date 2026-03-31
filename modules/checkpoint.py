"""
checkpoint.py — збереження та відновлення прогресу збору.

Файл checkpoint'у: collect_checkpoint.json у корені проєкту.
Структура: {"done": ["zahnarzt", ...], "total_saved": 1234}
"""

import json
import os

from config import CHECKPOINT_FILE


def load() -> tuple[set[str], int]:
    """
    Повертає (множина завершених slug-ів, загальна кількість збережених лікарів).
    Якщо файлу немає — повертає порожній стан.
    """
    if not os.path.exists(CHECKPOINT_FILE):
        return set(), 0

    with open(CHECKPOINT_FILE, encoding="utf-8") as f:
        data = json.load(f)

    done  = set(data.get("done", []))
    total = data.get("total_saved", 0)
    print(f"[CHECKPOINT] Відновлення: {len(done)} спеціальностей завершено, {total} лікарів збережено раніше.")
    return done, total


def save(done_slugs: set[str], total_saved: int) -> None:
    """Записує поточний прогрес у файл."""
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"done": list(done_slugs), "total_saved": total_saved},
            f,
            ensure_ascii=False,
            indent=2,
        )
