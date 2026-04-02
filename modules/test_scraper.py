"""
test_scraper.py — перевірка чи знаходить сайт картки лікарів
"""
import asyncio
import aiohttp
from bs4 import BeautifulSoup

URL = "https://www.docfinder.at/suche/hausarzt/1010?whatType=search_group&userSubmitted=1&originalWhat=Hausarzt&page=1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
}

async def test():
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(URL, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            print(f"Status: {resp.status}")
            print(f"URL: {resp.url}")
            html = await resp.text()

    soup = BeautifulSoup(html, "lxml")

    # Перевіряємо старий клас
    cards_old = soup.find_all("div", class_="card search-result")
    print(f"\nКарток (старий клас 'card search-result'): {len(cards_old)}")

    # Шукаємо будь-які div з 'search-result' в класі
    cards_any = soup.find_all("div", class_=lambda c: c and "search-result" in c)
    print(f"Карток (будь-який клас з 'search-result'): {len(cards_any)}")

    # Шукаємо будь-які div з 'card' в класі
    cards_card = soup.find_all("div", class_=lambda c: c and "card" in c)
    print(f"Div з класом 'card': {len(cards_card)}")

    # Виводимо перші 500 символів HTML для діагностики
    print(f"\n--- Перші 1000 символів HTML ---")
    print(html[:1000])

    # Якщо є картки — виводимо клас першої
    if cards_card:
        print(f"\n--- Клас першого div.card ---")
        print(cards_card[0].get("class"))

asyncio.run(test())
