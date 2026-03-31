import asyncio
import aiohttp
from bs4 import BeautifulSoup
import sys

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "https://www.docfinder.at/suche/zahnarzt/{city}?whatType=search_group&userSubmitted=1&originalWhat=Zahnarzt&page={page}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}

CITIES = [
    "wien", "graz", "linz", "salzburg", "innsbruck",
    "klagenfurt", "villach", "wels", "st-poelten", "dornbirn",
    "wiener-neustadt", "krems", "steyr", "feldkirch", "bregenz",
    "leoben", "klosterneuburg", "amstetten", "kapfenberg", "modling",
]

TARGET_COUNT = 500
CONCURRENCY = 10
PAGE_DELAY = 2.0


async def parse_page(session, city, page_number):
    """Fetch one search results page for a given city and return basic doctor dicts."""
    url = BASE_URL.format(city=city, page=page_number)
    print(f"  [>] {city} / page {page_number}: {url}")

    try:
        async with session.get(url) as response:
            response.raise_for_status()
            html = await response.text()
    except Exception as e:
        print(f"  [!] Failed to load {city} page {page_number}: {e}")
        return []

    soup = BeautifulSoup(html, "lxml")
    cards = soup.find_all("div", class_="card search-result")
    print(f"  [OK] Found {len(cards)} doctors ({city} p.{page_number})")

    doctors = []
    for card in cards:
        doc = extract_doctor(card)
        if doc:
            doctors.append(doc)
    return doctors


def extract_doctor(card):
    """Extract basic doctor data from a search result card."""
    doctor = {}

    try:
        name_tag = card.find("p", class_="shave")
        doctor["name"] = name_tag.text.strip() if name_tag else ""
    except Exception:
        doctor["name"] = ""

    try:
        link_tag = card.find("a", attrs={"aria-label": True})
        doctor["profile_url"] = "https://www.docfinder.at" + link_tag["href"]
    except Exception:
        doctor["profile_url"] = None

    try:
        doctor["rating"] = card.find("div", class_="stars")["title"]
    except Exception:
        doctor["rating"] = None

    try:
        doctor["reviews"] = card.find("span", class_="count").text.strip().strip("()")
    except Exception:
        doctor["reviews"] = None

    try:
        prof_tag = card.find("div", class_="professions")
        doctor["specialty"] = prof_tag.text.strip() if prof_tag else ""
    except Exception:
        doctor["specialty"] = None

    try:
        loc_tag = card.find("div", class_="location-text")
        doctor["address"] = loc_tag.text.strip() if loc_tag else ""
    except Exception:
        doctor["address"] = None

    try:
        tags = card.find_all("a", class_="tag")
        services = []
        for tag in tags:
            text = tag.text.strip()
            if text and text != "Mehr...":
                services.append(text)
        doctor["services"] = "; ".join(services)
    except Exception:
        doctor["services"] = None

    try:
        img_tag = card.find("img", style="opacity: 1;")
        if img_tag and img_tag.get("src"):
            doctor["photo_url"] = img_tag["src"].split("?")[0]
        else:
            doctor["photo_url"] = None
    except Exception:
        doctor["photo_url"] = None

    try:
        gallery_div = card.find("div", class_="gallery desktop hidden-md-down")
        gallery = []
        if gallery_div:
            for img in gallery_div.find_all("img"):
                src = img.get("data-src") or img.get("src")
                if src and not src.startswith("data:"):
                    gallery.append(src.split("?")[0])
        doctor["gallery"] = gallery if gallery else None
    except Exception:
        doctor["gallery"] = None

    try:
        appt_div = card.find("div", class_="book-appointment")
        if appt_div:
            appt_link = appt_div.find("a")
            if appt_link and appt_link.get("href"):
                doctor["appointment_url"] = appt_link["href"]
            else:
                doctor["appointment_url"] = None
        else:
            doctor["appointment_url"] = None
    except Exception:
        doctor["appointment_url"] = None

    return doctor


async def collect_all(session):
    """Iterate through cities and pages to collect up to TARGET_COUNT unique doctors."""
    all_doctors = []
    seen_urls = set()

    for city in CITIES:
        if len(all_doctors) >= TARGET_COUNT:
            break

        print(f"\n=== City: {city} (unique so far: {len(all_doctors)}/{TARGET_COUNT}) ===")
        page = 1

        while len(all_doctors) < TARGET_COUNT:
            doctors = await parse_page(session, city, page)

            if not doctors:
                print(f"  [!] No more results for {city}.")
                break

            added = 0
            for doc in doctors:
                url = doc.get("profile_url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_doctors.append(doc)
                    added += 1

            if added == 0:
                print(f"  [!] No new unique doctors on page {page} for {city}. Moving to next city.")
                break

            page += 1
            await asyncio.sleep(PAGE_DELAY)

    return all_doctors[:TARGET_COUNT]
