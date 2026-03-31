"""
collector.py — збір списків лікарів з пошукових сторінок docfinder.at.

Стратегія: для кожної спеціальності обходимо всі поштові індекси Австрії
(1000–9999). Індекси без результатів пропускаються після першого запиту.
Індекси з результатами пагінуються до кінця.
"""

import asyncio
import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import quote

from config import POSTAL_CODES, POSTAL_CONCURRENCY, PAGE_DELAY, REQUEST_TIMEOUT
from parser import extract_doctor


def _search_url(slug: str, display: str, postal_code: str, page: int) -> str:
    return (
        f"https://www.docfinder.at/suche/{slug}/{postal_code}"
        f"?whatType=search_group&userSubmitted=1"
        f"&originalWhat={quote(display)}&page={page}"
    )


async def _collect_one_code(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    slug: str,
    display: str,
    code: str,
) -> list[dict]:
    """
    Збирає всі сторінки для одного поштового індексу.
    Повертає список лікарів (може бути порожнім).
    """
    doctors: list[dict] = []
    seen: set[str] = set()
    page = 1

    async with sem:
        while True:
            url = _search_url(slug, display, code, page)
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                ) as resp:
                    resp.raise_for_status()
                    html = await resp.text()
            except Exception as e:
                print(f"  [!] {code} стор.{page}: {e}")
                break

            soup = BeautifulSoup(html, "lxml")
            cards = soup.find_all("div", class_="card search-result")

            if not cards:
                break  # порожній код або кінець пагінації

            added = 0
            for card in cards:
                doc = extract_doctor(card)
                url_val = doc.get("profile_url")
                if url_val and url_val not in seen:
                    seen.add(url_val)
                    doctors.append(doc)
                    added += 1

            if added == 0:
                break  # всі картки вже бачили — кінець

            page += 1
            await asyncio.sleep(PAGE_DELAY)

    if doctors:
        print(f"  [+] {code}: {len(doctors)} лікарів")

    return doctors


async def collect_specialty(
    session: aiohttp.ClientSession,
    slug: str,
    display: str,
) -> list[dict]:
    """
    Збирає всіх лікарів по спеціальності через всі поштові індекси паралельно.
    Повертає дедублікований список.
    """
    sem = asyncio.Semaphore(POSTAL_CONCURRENCY)
    tasks = [
        _collect_one_code(session, sem, slug, display, code)
        for code in POSTAL_CODES
    ]

    seen: set[str] = set()
    all_doctors: list[dict] = []

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            continue
        for doc in result:
            url = doc.get("profile_url")
            if url and url not in seen:
                seen.add(url)
                all_doctors.append(doc)

    return all_doctors
