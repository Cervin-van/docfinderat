"""
verify_slugs.py — перевіряє які slug-и спеціальностей реально працюють на docfinder.at.

Для кожної спеціальності робить 1 запит на /suche/{slug}/1010 і рахує картки лікарів.

Результат:
  ✓  — slug працює, є результати
  →  — slug перенаправляє на іншу URL (але може все одно мати результати)
  ✗  — slug порожній або не існує

Запуск:
    python modules/verify_slugs.py
"""

import asyncio
import aiohttp
import sys
import os
from bs4 import BeautifulSoup
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(__file__))
from config import SPECIALTIES, HEADERS


async def check_one(session: aiohttp.ClientSession, sem: asyncio.Semaphore, slug: str, display: str):
    url = (
        f"https://www.docfinder.at/suche/{slug}/1010"
        f"?whatType=search_group&userSubmitted=1&originalWhat={quote(display)}&page=1"
    )

    async with sem:
        try:
            async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                final_url = str(resp.url)
                html = await resp.text()
        except Exception as e:
            return slug, display, 0, f"✗ ERROR", str(e)

    soup = BeautifulSoup(html, "lxml")
    cards = len(soup.find_all("div", class_="card search-result"))

    was_redirected = (slug not in final_url.split("docfinder.at/suche/")[-1].split("/")[0]
                      if "docfinder.at/suche/" in final_url else True)

    if cards > 0:
        marker = "→ ✓" if was_redirected else "✓ "
    else:
        marker = "→ ✗" if was_redirected else "✗ "

    return slug, display, cards, marker, final_url


async def main():
    sem = asyncio.Semaphore(8)
    connector = aiohttp.TCPConnector(limit=8)

    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        tasks = [check_one(session, sem, slug, display) for slug, display in SPECIALTIES]
        results = await asyncio.gather(*tasks)

    results = sorted(results, key=lambda x: x[3] + x[0])  # сортуємо: спочатку робочі

    print(f"\n{'Slug':<45} {'Карток':>7}  Статус")
    print("─" * 70)
    for slug, display, cards, marker, final_url in results:
        redirected_note = f"  →  {final_url[:60]}" if "→" in marker else ""
        print(f"{slug:<45} {cards:>7}  {marker}{redirected_note}")

    working   = sum(1 for *_, marker, __ in results if "✓" in marker)
    redirected = sum(1 for *_, marker, __ in results if "→" in marker)
    empty     = sum(1 for *_, marker, __ in results if "✗" in marker)

    print("─" * 70)
    print(f"✓  Працює        : {working}")
    print(f"→  Редирект      : {redirected}  (перевірте вручну)")
    print(f"✗  Порожній/404  : {empty}  (slug неправильний)")
    print(f"Всього           : {len(results)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
