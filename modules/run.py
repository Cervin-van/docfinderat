"""
run.py — точка входу для повного збору лікарів з docfinder.at.

Алгоритм:
  Для кожної спеціальності зі списку SPECIALTIES:
    1. Збираємо базові дані по всіх поштових індексах Австрії (1000–9999)
    2. Збагачуємо профілі лікарів (паралельно)
    3. Зберігаємо в PostgreSQL + JSON
    4. Записуємо checkpoint

Відновлення після зупинки:
    Просто запустіть знову — завершені спеціальності пропускаються.

Щоб почати з нуля:
    Видаліть collect_checkpoint.json у корені проєкту.

Запуск:
    python modules/run.py
"""

import sys
import os
import asyncio
import aiohttp

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import load_django  # noqa: F401 — ініціалізує Django ORM

sys.stdout.reconfigure(encoding="utf-8")

from asgiref.sync import sync_to_async

import checkpoint
import saver
from collector import collect_specialty
from parser import fetch_profile
from config import SPECIALTIES, HEADERS, POSTAL_CONCURRENCY, PROFILE_CONCURRENCY, POSTAL_CODES


async def enrich(session: aiohttp.ClientSession, doctors: list[dict]) -> list[dict]:
    """Паралельно збагачує профілі лікарів."""
    sem = asyncio.Semaphore(PROFILE_CONCURRENCY)
    tasks = [fetch_profile(session, sem, doc) for doc in doctors]

    enriched = []
    for coro in asyncio.as_completed(tasks):
        doc = await coro
        enriched.append(doc)
        if len(enriched) % 100 == 0 or len(enriched) == len(doctors):
            print(f"  [{len(enriched)}/{len(doctors)}] профілів оброблено...")

    return enriched


async def main() -> None:
    done_slugs, total_saved = checkpoint.load()

    pending = [(slug, display) for slug, display in SPECIALTIES if slug not in done_slugs]

    if not pending:
        print("[DONE] Усі спеціальності вже оброблені.")
        print(f"[DONE] Щоб почати знову — видаліть collect_checkpoint.json")
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
            print(f"[1/3] Зібрано: {len(doctors)} унікальних лікарів\n")

            if not doctors:
                print(f"[SKIP] Лікарів не знайдено — пропускаємо.\n")
                done_slugs.add(slug)
                checkpoint.save(done_slugs, total_saved)
                continue

            # ── Етап 2: збагачення профілів ───────────────────────────────
            print(f"[2/3] Збагачуємо профілі ({PROFILE_CONCURRENCY} паралельно)...")
            enriched = await enrich(session, doctors)

            # Дедублікація після збагачення
            seen: set[str] = set()
            unique: list[dict] = []
            for d in enriched:
                url = d.get("profile_url")
                if url and url not in seen:
                    seen.add(url)
                    unique.append(d)
            print(f"[2/3] Унікальних після збагачення: {len(unique)}\n")

            # ── Етап 3: збереження ────────────────────────────────────────
            print(f"[3/3] Зберігаємо в БД та JSON...")
            batch_saved = await sync_to_async(saver.save_to_db)(unique)
            await sync_to_async(saver.save_to_json)(unique)

            total_saved += batch_saved
            print(f"[3/3] Збережено: {batch_saved}  |  Всього в БД: {total_saved}\n")

            # ── Checkpoint ────────────────────────────────────────────────
            done_slugs.add(slug)
            checkpoint.save(done_slugs, total_saved)
            print(f"[✓] {display} завершено. Прогрес: {len(done_slugs)}/{len(SPECIALTIES)} спеціальностей.")

    print(f"\n{'='*60}")
    print(f"[DONE] Збір завершено!")
    print(f"[DONE] Всього збережено: {total_saved} лікарів")
    print(f"[DONE] Оброблено спеціальностей: {len(done_slugs)}/{len(SPECIALTIES)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
