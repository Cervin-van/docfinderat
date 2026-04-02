"""
3_collect_all_doctors.py — збір усіх лікарів з docfinder.at за поштовими індексами.

Точка входу: запустіть напряму — python modules/3_collect_all_doctors.py

Алгоритм:
  Для кожної спеціальності зі списку SPECIALTIES:
    1. Паралельний збір по всіх поштових індексах Австрії (1000–9999)
    2. Паралельне збагачення профілів лікарів
    3. Збереження в PostgreSQL + JSON
    4. Запис checkpoint-у для відновлення після зупинки

Відновлення після зупинки — просто запустіть знову, завершені спеціальності пропускаються.
Почати з нуля — видаліть collect_checkpoint.json у корені проєкту.
"""

import sys
import os
import json
import asyncio
import importlib
import aiohttp
from decimal import Decimal, InvalidOperation

# Bootstrap: налаштовуємо sys.path і Django ORM
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import load_django  # noqa: F401 — ініціалізує Django ORM

sys.stdout.reconfigure(encoding="utf-8")

from asgiref.sync import sync_to_async
from parser_app.models import Doctor, DoctorGallery

from config import (
    SPECIALTIES, POSTAL_CODES, HEADERS,
    POSTAL_CONCURRENCY, PROFILE_CONCURRENCY,
    CHECKPOINT_FILE, JSON_DIR,
)

_parse = importlib.import_module("1_parse_page")
fetch_profile = _parse.fetch_profile

_paginate = importlib.import_module("2_paginate_postal")
collect_postal_code = _paginate.collect_postal_code


# ─── Збір по спеціальності ────────────────────────────────────────────────────

async def collect_specialty(
    session: aiohttp.ClientSession,
    slug: str,
    display: str,
) -> list[dict]:
    """
    Паралельно збирає лікарів по всіх поштових індексах для однієї спеціальності.
    Дедублікує тільки в межах цієї категорії (один і той же лікар може бути
    в кількох категоріях і буде збережений окремо для кожної).
    """
    sem = asyncio.Semaphore(POSTAL_CONCURRENCY)
    tasks = [
        collect_postal_code(session, sem, slug, display, code)
        for code in POSTAL_CODES
    ]

    seen: set[str] = set()
    all_doctors: list[dict] = []
    raw_count = 0

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            continue
        for doc in result:
            raw_count += 1
            url = doc.get("profile_url")
            if url and url not in seen:
                seen.add(url)
                all_doctors.append(doc)

    print(f"  Всього з поштових індексів (з дублями): {raw_count}")
    print(f"  Унікальних в межах категорії:           {len(all_doctors)}")
    return all_doctors


# ─── Збагачення профілів ──────────────────────────────────────────────────────

async def enrich(session: aiohttp.ClientSession, doctors: list[dict]) -> list[dict]:
    """Паралельно завантажує профільні сторінки та збагачує дані лікарів."""
    sem = asyncio.Semaphore(PROFILE_CONCURRENCY)
    tasks = [fetch_profile(session, sem, doc) for doc in doctors]

    enriched = []
    for coro in asyncio.as_completed(tasks):
        doc = await coro
        enriched.append(doc)
        if len(enriched) % 100 == 0 or len(enriched) == len(doctors):
            print(f"  [{len(enriched)}/{len(doctors)}] профілів оброблено...")

    return enriched


# ─── Збереження в PostgreSQL ──────────────────────────────────────────────────

def save_to_db(doctors: list[dict]) -> int:
    """
    Зберігає лікарів у PostgreSQL через update_or_create.
    Не видаляє існуючі записи. Повертає кількість збережених записів.
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


# ─── Збереження в JSON ────────────────────────────────────────────────────────

def save_to_json(doctors: list[dict], slug: str) -> None:
    """
    Зберігає лікарів спеціальності у json/{slug}.json.
    Якщо файл вже існує — додає нових (дедублікація по profile_url).
    """
    os.makedirs(JSON_DIR, exist_ok=True)
    filepath = os.path.join(JSON_DIR, f"{slug}.json")

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


def update_stats(slug: str, display: str, count: int) -> None:
    """
    Оновлює json/_stats.json — загальна статистика збору:
      - total: скільки всього лікарів спаршено
      - fields: список полів, які збираються
      - specialties: словник {slug: {display, count}} по кожній спеціальності
    """
    os.makedirs(JSON_DIR, exist_ok=True)
    stats_file = os.path.join(JSON_DIR, "_stats.json")

    stats: dict = {}
    if os.path.exists(stats_file):
        try:
            with open(stats_file, encoding="utf-8") as f:
                stats = json.load(f)
        except (json.JSONDecodeError, OSError):
            stats = {}

    # Поля, які збираються парсером (фіксований перелік)
    stats["fields"] = [
        "name", "profile_url", "rating", "reviews", "specialty",
        "address", "services", "photo_url", "gallery", "appointment_url",
        "phone", "fax", "email", "website", "description",
        "address_full", "zip_code", "city", "opening_hours",
        "latitude", "longitude", "photo_url_full",
    ]

    specialties = stats.get("specialties", {})
    prev_count = specialties.get(slug, {}).get("count", 0)
    specialties[slug] = {"display": display, "count": count}
    stats["specialties"] = specialties
    stats["total"] = sum(s["count"] for s in specialties.values())

    # Оновлюємо дельту у total якщо запис вже існував
    if prev_count != count:
        stats["total"] = stats["total"] - prev_count + count

    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


# ─── Checkpoint ───────────────────────────────────────────────────────────────

def checkpoint_load() -> tuple[set[str], int]:
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


def checkpoint_save(done_slugs: set[str], total_saved: int) -> None:
    """Записує поточний прогрес у файл."""
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"done": list(done_slugs), "total_saved": total_saved},
            f,
            ensure_ascii=False,
            indent=2,
        )


# ─── Головна функція ──────────────────────────────────────────────────────────

async def main() -> None:
    # Якщо передано аргумент --slug hausarzt — обробити лише одну спеціальність
    only_slug = None
    if "--slug" in sys.argv:
        only_slug = sys.argv[sys.argv.index("--slug") + 1]
        match = next(((s, d) for s, d in SPECIALTIES if s == only_slug), None)
        if not match:
            print(f"[ERROR] Slug '{only_slug}' не знайдено в SPECIALTIES.")
            print(f"Доступні: {', '.join(s for s, _ in SPECIALTIES)}")
            return
        pending = [match]
        done_slugs, total_saved = set(), 0
    else:
        done_slugs, total_saved = checkpoint_load()
        pending = [(slug, display) for slug, display in SPECIALTIES if slug not in done_slugs]

    if not pending:
        print("[DONE] Усі спеціальності вже оброблені.")
        print("[DONE] Щоб почати знову — видаліть collect_checkpoint.json")
        return

    print(f"\n{'='*60}")
    print(f"[START] Спеціальностей до обробки : {len(pending)} / {len(SPECIALTIES)}")
    print(f"[START] Поштових індексів          : {len(POSTAL_CODES)}")
    print(f"[START] Паралельність індексів     : {POSTAL_CONCURRENCY}")
    print(f"[START] Паралельність профілів     : {PROFILE_CONCURRENCY}")
    print(f"[START] Вже збережено лікарів      : {total_saved}")
    print(f"{'='*60}\n")

    connector = aiohttp.TCPConnector(limit=max(POSTAL_CONCURRENCY, PROFILE_CONCURRENCY))
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        for idx, (slug, display) in enumerate(pending, 1):
            print(f"\n{'─'*60}")
            print(f"[{idx}/{len(pending)}] {display}  (slug: {slug})")
            print(f"{'─'*60}")

            # ── Етап 1: збір списків ──────────────────────────────────────
            print(f"[1/3] Збираємо список по {len(POSTAL_CODES)} індексах...")
            doctors = await collect_specialty(session, slug, display)
            print(f"[1/3] Буде оброблено: {len(doctors)} лікарів\n")

            if not doctors:
                print("[SKIP] Лікарів не знайдено — пропускаємо.\n")
                done_slugs.add(slug)
                checkpoint_save(done_slugs, total_saved)
                continue

            # ── Перевірка скільки вже є в БД ─────────────────────────────
            urls = [d["profile_url"] for d in doctors if d.get("profile_url")]
            existing_count = await sync_to_async(
                lambda: Doctor.objects.filter(profile_url__in=urls).count()
            )()
            new_count = len(doctors) - existing_count
            print(f"  В БД вже існує : {existing_count} (будуть оновлені)")
            print(f"  Нових для БД   : {new_count} (будуть створені)")
            print(f"  Всього в БД    : {total_saved}\n")

            # ── Етап 2+3: збагачення і збереження пачками ────────────────
            BATCH = 100
            print(f"[2/3] Збагачуємо профілі пачками по {BATCH} ({PROFILE_CONCURRENCY} паралельно)...")

            all_unique: list[dict] = []
            batch_saved = 0

            for i in range(0, len(doctors), BATCH):
                chunk = doctors[i : i + BATCH]
                enriched_chunk = await enrich(session, chunk)

                if enriched_chunk:
                    saved = await sync_to_async(save_to_db)(enriched_chunk)
                    batch_saved += saved
                    total_saved += saved
                    all_unique.extend(enriched_chunk)
                    print(f"  [пачка {i//BATCH + 1}] отримано {len(enriched_chunk)}, збережено {saved} | Всього в БД: {total_saved}")

            await sync_to_async(save_to_json)(all_unique, slug)
            await sync_to_async(update_stats)(slug, display, len(all_unique))
            print(f"[3/3] Категорія завершена: отримано {len(all_unique)}, збережено/оновлено {batch_saved} | Всього в БД: {total_saved}\n")

            # ── Checkpoint ────────────────────────────────────────────────
            done_slugs.add(slug)
            checkpoint_save(done_slugs, total_saved)
            print(f"[✓] {display} завершено. Прогрес: {len(done_slugs)}/{len(SPECIALTIES)} спеціальностей.")

    print(f"\n{'='*60}")
    print("[DONE] Збір завершено!")
    print(f"[DONE] Всього збережено: {total_saved} лікарів")
    print(f"[DONE] Оброблено спеціальностей: {len(done_slugs)}/{len(SPECIALTIES)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
