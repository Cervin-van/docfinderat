"""
saver.py — збереження зібраних лікарів у PostgreSQL та JSON.

Важливо: цей модуль імпортує Django-моделі, тому load_django
має бути викликаний ДО імпорту saver (це робить run.py).
"""

import json
import os
from decimal import Decimal, InvalidOperation

from parser_app.models import Doctor, DoctorGallery
from config import JSON_OUTPUT


def save_to_db(doctors: list[dict]) -> int:
    """
    Зберігає лікарів у PostgreSQL через update_or_create.
    Не видаляє існуючі записи.
    Повертає кількість збережених записів.
    """
    saved = 0
    for raw in doctors:
        d = raw.copy()
        gallery_urls = d.pop("gallery", None)

        try:
            reviews = int(d.pop("reviews", None) or 0) or None
        except (ValueError, TypeError):
            reviews = None

        try:
            latitude = Decimal(str(d.pop("latitude", None) or "")) or None
        except InvalidOperation:
            latitude = None
            d.pop("latitude", None)

        try:
            longitude = Decimal(str(d.pop("longitude", None) or "")) or None
        except InvalidOperation:
            longitude = None
            d.pop("longitude", None)

        profile_url = d.pop("profile_url", None)
        if not profile_url:
            continue

        doctor_obj, created = Doctor.objects.update_or_create(
            profile_url=profile_url,
            defaults={**d, "reviews": reviews, "latitude": latitude, "longitude": longitude},
        )

        if created and gallery_urls:
            for url in gallery_urls:
                DoctorGallery.objects.get_or_create(doctor=doctor_obj, photo_url=url)

        saved += 1

    return saved


def save_to_json(doctors: list[dict], filepath: str = JSON_OUTPUT) -> None:
    """
    Дозаписує лікарів до JSON-файлу.
    Якщо файл вже існує — завантажує поточний список і додає нових (по profile_url).
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    existing: list[dict] = []
    if os.path.exists(filepath):
        try:
            with open(filepath, encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = []

    existing_urls = {d.get("profile_url") for d in existing}
    new_entries = [d for d in doctors if d.get("profile_url") not in existing_urls]

    if not new_entries:
        return

    existing.extend(new_entries)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
