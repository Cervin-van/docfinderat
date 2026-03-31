"""
2_paginate_postal.py — пагінація результатів для одного поштового індексу.

Дві функції:
  _search_url(slug, display, postal_code, page) — будує URL пошукового запиту
  collect_postal_code(session, sem, slug, display, code) — обходить всі
      сторінки одного поштового індексу і повертає список лікарів
"""

import importlib
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import quote

from config import PAGE_DELAY, REQUEST_TIMEOUT, MAX_PAGES

_parse = importlib.import_module("1_parse_page")
extract_doctor = _parse.extract_doctor


def _search_url(slug: str, display: str, postal_code: str, page: int) -> str:
    return (
        f"https://www.docfinder.at/suche/{slug}/{postal_code}"
        f"?whatType=search_group&userSubmitted=1"
        f"&originalWhat={quote(display)}&page={page}"
    )


async def collect_postal_code(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    slug: str,
    display: str,
    code: str,
) -> list[dict]:
    """
    Збирає сторінки результатів для одного поштового індексу (до MAX_PAGES).
    Зупиняється при порожній сторінці, дублях або досягненні ліміту сторінок.
    Повертає список лікарів (може бути порожнім).
    """
    doctors: list[dict] = []
    seen: set[str] = set()
    page = 1

    async with sem:
        while page <= MAX_PAGES:
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
                break  # порожній індекс або кінець пагінації

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
