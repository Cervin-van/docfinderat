"""
4_collect_by_city.py — збір лікарів з docfinder.at по містах.

Стратегія: спеціальність → всі міста → всі сторінки → збагачення → БД + JSON

Запуск:
  python modules/4_collect_by_city.py
  python modules/4_collect_by_city.py --slug zahnarzt
"""

import sys
import os
import json
import asyncio
import importlib
import aiohttp
from decimal import Decimal, InvalidOperation

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import load_django  # noqa: F401

sys.stdout.reconfigure(encoding="utf-8")

from asgiref.sync import sync_to_async
from parser_app.models import Doctor, DoctorGallery

from config import (
    SPECIALTIES, CITIES, HEADERS,
    POSTAL_CONCURRENCY, PROFILE_CONCURRENCY,
    PAGE_DELAY,
)

_parse = importlib.import_module("1_parse_page")
fetch_profile = _parse.fetch_profile

_paginate = importlib.import_module("2_paginate_city")
collect_city = _paginate.collect_city

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
CITIES_JSON_DIR = os.path.join(_ROOT, "json", "cities_data")
CHECKPOINT_FILE = os.path.join(_ROOT, "json", "cities_checkpoint", "collect_cities_checkpoint.json")


# ─── Збір по спеціальності ────────────────────────────────────────────────────

async def collect_specialty(session: aiohttp.ClientSession, slug: str, display: str) -> list[dict]:
    sem = asyncio.Semaphore(POSTAL_CONCURRENCY)
    tasks = [
        asyncio.ensure_future(collect_city(session, sem, slug, display, city))
        for city in CITIES
    ]

    seen: set[str] = set()
    doctors: list[dict] = []
    raw_total = 0
    cities_done = 0
    cities_with_results = 0
    errors = 0
    total = len(tasks)

    for coro in asyncio.as_completed(tasks):
        try:
            result = await coro
        except BaseException as e:
            print(f"  [!] Помилка збору міста: {e}")
            errors += 1
            cities_done += 1
            continue

        cities_done += 1
        if result:
            cities_with_results += 1
            for doc in result:
                raw_total += 1
                url = doc.get("profile_url")
                if not url:
                    continue
                url_key = url.rstrip("/").lower()
                if url_key not in seen:
                    seen.add(url_key)
                    doc["profile_url"] = url.rstrip("/")
                    doctors.append(doc)

        if cities_done % 10 == 0:
            print(f"  --- {cities_done}/{total} міст оброблено | унікальних: {len(doctors)} ---")

    print(f"  Міст з результатами     : {cities_with_results} із {total}")
    if errors:
        print(f"  Помилок при зборі       : {errors}")
    print(f"  Знайдено (з дублями)    : {raw_total}")
    print(f"  Унікальних лікарів      : {len(doctors)}")
    return doctors


# ─── Збагачення профілів ──────────────────────────────────────────────────────

async def enrich(session: aiohttp.ClientSession, doctors: list[dict]) -> list[dict]:
    sem = asyncio.Semaphore(PROFILE_CONCURRENCY)
    tasks = [fetch_profile(session, sem, doc) for doc in doctors]

    enriched = []
    for coro in asyncio.as_completed(tasks):
        doc = await coro
        enriched.append(doc)
        if len(enriched) % 50 == 0 or len(enriched) == len(doctors):
            print(f"    збагачено {len(enriched)}/{len(doctors)}...")

    return enriched


# ─── Збереження в PostgreSQL ──────────────────────────────────────────────────

def save_to_db(doctors: list[dict]) -> tuple[int, int]:
    created_count = 0
    updated_count = 0

    for raw in doctors:
        d = raw.copy()
        gallery_urls = d.pop("gallery", None)

        try:
            reviews = int(d.pop("reviews", None) or 0) or None
        except (ValueError, TypeError):
            reviews = None

        lat_raw = d.pop("latitude", None)
        lon_raw = d.pop("longitude", None)
        try:
            latitude = Decimal(str(lat_raw)) if lat_raw else None
        except InvalidOperation:
            latitude = None
        try:
            longitude = Decimal(str(lon_raw)) if lon_raw else None
        except InvalidOperation:
            longitude = None

        profile_url = d.pop("profile_url", None)
        if not profile_url:
            continue

        search_slug = d.pop("search_slug", "")

        obj, created = Doctor.objects.update_or_create(
            profile_url=profile_url,
            search_slug=search_slug,
            defaults={**d, "reviews": reviews, "latitude": latitude, "longitude": longitude},
        )

        if created:
            created_count += 1
        else:
            updated_count += 1

        if gallery_urls:
            for url in gallery_urls:
                DoctorGallery.objects.get_or_create(doctor=obj, photo_url=url)

    return created_count, updated_count


# ─── Збереження в JSON ────────────────────────────────────────────────────────

def save_to_json(doctors: list[dict], slug: str) -> None:
    os.makedirs(CITIES_JSON_DIR, exist_ok=True)
    filepath = os.path.join(CITIES_JSON_DIR, f"{slug}.json")

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
    os.makedirs(CITIES_JSON_DIR, exist_ok=True)
    stats_file = os.path.join(CITIES_JSON_DIR, "_stats.json")

    stats: dict = {}
    if os.path.exists(stats_file):
        try:
            with open(stats_file, encoding="utf-8") as f:
                stats = json.load(f)
        except (json.JSONDecodeError, OSError):
            stats = {}

    specialties = stats.get("specialties", {})
    if slug not in specialties:
        specialties[slug] = {"display": display, "count": count}
    else:
        specialties[slug]["count"] = specialties[slug].get("count", 0) + count
        
    stats["specialties"] = specialties
    stats["total"] = sum(s["count"] for s in specialties.values())

    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


# ─── Checkpoint ───────────────────────────────────────────────────────────────

def checkpoint_load() -> tuple[set[str], int]:
    checkpoint_dir = os.path.dirname(CHECKPOINT_FILE)
    os.makedirs(checkpoint_dir, exist_ok=True)
    if not os.path.exists(CHECKPOINT_FILE):
        return set(), 0
    with open(CHECKPOINT_FILE, encoding="utf-8") as f:
        data = json.load(f)
    done = set(data.get("done", []))
    total = data.get("total_saved", 0)
    print(f"[CHECKPOINT] Відновлення: {len(done)} спеціальностей завершено, {total} записів в БД раніше.")
    return done, total


def checkpoint_save(done_slugs: set[str], total_saved: int) -> None:
    checkpoint_dir = os.path.dirname(CHECKPOINT_FILE)
    os.makedirs(checkpoint_dir, exist_ok=True)
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump({"done": list(done_slugs), "total_saved": total_saved}, f, ensure_ascii=False, indent=2)


# ─── Точка входу ─────────────────────────────────────────────────────────────

async def main() -> None:
    if "--slug" in sys.argv:
        only_slug = sys.argv[sys.argv.index("--slug") + 1]
        match = next(((s, d) for s, d in SPECIALTIES if s == only_slug), None)
        if not match:
            print(f"[ERROR] Slug '{only_slug}' не знайдено.")
            print(f"Доступні: {', '.join(s for s, _ in SPECIALTIES)}")
            return
        pending = [match]
        done_slugs, total_db = set(), 0
    else:
        done_slugs, total_db = checkpoint_load()
        pending = [(s, d) for s, d in SPECIALTIES if s not in done_slugs]

    if not pending:
        print(f"[DONE] Всі спеціальності оброблені. Щоб почати знову — видаліть {CHECKPOINT_FILE}")
        return

    total_db = await sync_to_async(Doctor.objects.count)()

    print(f"\n{'='*60}")
    print(f"  Спеціальностей до обробки : {len(pending)} / {len(SPECIALTIES)}")
    print(f"  Міст                      : {len(CITIES)}")
    print(f"  Паралельність міст        : {POSTAL_CONCURRENCY}")
    print(f"  Паралельність профілів    : {PROFILE_CONCURRENCY}")
    print(f"  Записів в БД зараз        : {total_db}")
    print(f"{'='*60}\n")

    BATCH = 100

    connector = aiohttp.TCPConnector(limit=max(POSTAL_CONCURRENCY, PROFILE_CONCURRENCY))
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:

        for idx, (slug, display) in enumerate(pending, 1):
            print(f"\n{'─'*60}")
            print(f"[{idx}/{len(pending)}] {display}  (slug: {slug})")
            print(f"{'─'*60}")

            print(f"[Збір] по {len(CITIES)} містах...")
            doctors = await collect_specialty(session, slug, display)
            for doc in doctors:
                doc["search_slug"] = slug

            if not doctors:
                print("[ПРОПУСК] Лікарів не знайдено.\n")
                done_slugs.add(slug)
                checkpoint_save(done_slugs, total_db)
                continue

            print(f"\n[Збагачення + збереження] пачками по {BATCH}...")
            all_enriched: list[dict] = []
            spec_created = 0
            spec_updated = 0

            for i in range(0, len(doctors), BATCH):
                chunk = doctors[i : i + BATCH]
                batch_num = i // BATCH + 1
                total_batches = (len(doctors) + BATCH - 1) // BATCH
                print(f"  Пачка {batch_num}/{total_batches} ({len(chunk)} лікарів):")

                enriched = await enrich(session, chunk)
                created, updated = await sync_to_async(save_to_db)(enriched)

                spec_created += created
                spec_updated += updated
                total_db += created
                all_enriched.extend(enriched)

                print(f"    → нових: {created}, оновлених: {updated} | Всього в БД: {total_db}")

            await sync_to_async(save_to_json)(all_enriched, slug)
            await sync_to_async(update_stats)(slug, display, len(all_enriched))

            print(f"\n[✓] {display}: зібрано {len(doctors)}, нових {spec_created}, оновлених {spec_updated}")
            print(f"    Всього в БД: {total_db}")

            done_slugs.add(slug)
            checkpoint_save(done_slugs, total_db)

    print(f"\n{'='*60}")
    print(f"[DONE] Збір завершено! Записів в БД: {total_db}")
    print(f"[DONE] Оброблено спеціальностей: {len(done_slugs)}/{len(SPECIALTIES)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
