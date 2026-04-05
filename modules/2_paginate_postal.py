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

RETRY_COUNT = 3       # скільки разів повторювати при помилці
RETRY_DELAY = 2.0     # затримка між спробами (секунди)
INTERNET_CHECK_INTERVAL = 10  # як часто перевіряти інтернет (секунди)


async def _wait_for_internet() -> None:
    """Блокує виконання поки інтернет недоступний. Перевіряє через TCP до 8.8.8.8:53."""
    first = True
    while True:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection("8.8.8.8", 53),
                timeout=3,
            )
            writer.close()
            if not first:
                print("  [✓] Інтернет відновлено, продовжуємо...")
            return
        except Exception:
            if first:
                print(f"  [⚠] Інтернет недоступний — чекаємо відновлення (перевірка кожні {INTERNET_CHECK_INTERVAL}с)...")
                first = False
            await asyncio.sleep(INTERNET_CHECK_INTERVAL)


def _search_url(slug: str, display: str, postal_code: str, page: int) -> str:
    return (
        f"https://www.docfinder.at/suche/{slug}/{postal_code}"
        f"?whatType=search_group&userSubmitted=1"
        f"&originalWhat={quote(display)}&page={page}"
    )


_CONN_ERRORS = (
    aiohttp.ClientConnectorError,
    aiohttp.ServerDisconnectedError,
    asyncio.TimeoutError,
)


async def _fetch_page(session: aiohttp.ClientSession, sem: asyncio.Semaphore, url: str, code: str, page: int) -> str | None:
    """Завантажує одну сторінку з retry. При втраті інтернету — чекає необмежено.
    Повертає HTML або None при HTTP-помилці після всіх спроб."""
    http_errors = 0
    while True:
        try:
            async with sem:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                ) as resp:
                    resp.raise_for_status()
                    return await resp.text()
        except _CONN_ERRORS:
            # Помилка з'єднання — чекаємо інтернет, потім повторюємо без ліміту
            await _wait_for_internet()
        except aiohttp.ClientResponseError as e:
            if e.status == 500:
                # Сервер повертає 500 на неіснуючих сторінках — кінець пагінації
                return None
            # Інші HTTP-помилки — обмежений retry
            http_errors += 1
            if http_errors < RETRY_COUNT:
                print(f"  [!] {code} стор.{page} спроба {http_errors}/{RETRY_COUNT}: {e} — повтор через {RETRY_DELAY}с")
                await asyncio.sleep(RETRY_DELAY)
            else:
                print(f"  [!] {code} стор.{page}: всі {RETRY_COUNT} спроби невдалі — {e}")
                return None
        except Exception as e:
            http_errors += 1
            if http_errors < RETRY_COUNT:
                print(f"  [!] {code} стор.{page} спроба {http_errors}/{RETRY_COUNT}: {e} — повтор через {RETRY_DELAY}с")
                await asyncio.sleep(RETRY_DELAY)
            else:
                print(f"  [!] {code} стор.{page}: всі {RETRY_COUNT} спроби невдалі — {e}")
                return None


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
    pages_fetched = 0

    while page <= MAX_PAGES:
        url = _search_url(slug, display, code, page)
        html = await _fetch_page(session, sem, url, code, page)

        if html is None:
            break  # всі спроби невдалі

        pages_fetched += 1
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
        if page <= MAX_PAGES:
            await asyncio.sleep(PAGE_DELAY)

    print(f"  [{code}] {len(doctors)} лікарів | {pages_fetched} стор.")

    return doctors
