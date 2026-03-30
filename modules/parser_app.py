import asyncio
import aiohttp
from bs4 import BeautifulSoup
import json
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "https://www.docfinder.at/suche/zahnarzt?whatType=search_group&userSubmitted=1&originalWhat=Zahnarzt&page={page}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}

TARGET_COUNT = 10
CONCURRENCY = 10
PAGE_DELAY = 2.0

OUTPUT_DIR = "json"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "doctors.json")


async def parse_page(session, page_number):
    """Fetch one search results page and return a list of basic doctor dicts."""
    url = BASE_URL.format(page=page_number)
    print(f"  [>] Page {page_number}: {url}")

    try:
        async with session.get(url) as response:
            response.raise_for_status()
            html = await response.text()
    except Exception as e:
        print(f"  [!] Failed to load page {page_number}: {e}")
        return []

    soup = BeautifulSoup(html, "lxml")
    cards = soup.find_all("div", class_="card search-result")
    print(f"  [OK] Found {len(cards)} doctors on page {page_number}")

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


async def fetch_profile(session, semaphore, doctor):
    """Fetch the doctor's profile page and enrich the doctor dict with full data."""
    profile = {
        "phone": None,
        "fax": None,
        "email": None,
        "website": None,
        "description": None,
        "address_full": None,
        "zip_code": None,
        "city": None,
        "opening_hours": None,
        "latitude": None,
        "longitude": None,
        "photo_url_full": None,
    }

    profile_url = doctor.get("profile_url")
    if not profile_url:
        return doctor

    async with semaphore:
        try:
            async with session.get(
                profile_url, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                response.raise_for_status()
                html = await response.text()
        except Exception as e:
            print(f"  [!] Failed to load profile {doctor.get('name', '?')}: {e}")
            doctor.update(profile)
            return doctor

    soup = BeautifulSoup(html, "lxml")

    try:
        link = soup.select_one('a[href^="tel:"]')
        if link:
            profile["phone"] = link.get_text(strip=True)
    except Exception:
        pass

    try:
        link = soup.select_one('a[href^="fax:"]')
        if link:
            profile["fax"] = link.get_text(strip=True)
    except Exception:
        pass

    try:
        link = soup.select_one('a[href^="mailto:"]')
        if link:
            profile["email"] = link.get_text(strip=True)
    except Exception:
        pass

    try:
        data = {}
        for script_tag in soup.find_all("script", {"type": "application/ld+json"}):
            if not script_tag.string:
                continue
            parsed = json.loads(script_tag.string)
            if "mainEntity" in parsed:
                data = parsed["mainEntity"]
                break

        if data:
            try:
                addr = data.get("address", {})
                profile["address_full"] = addr.get("streetAddress")
                profile["zip_code"] = addr.get("postalCode")
                profile["city"] = addr.get("addressLocality")
            except Exception:
                pass

            try:
                profile["website"] = data.get("url")
            except Exception:
                pass

            try:
                profile["description"] = data.get("description")
            except Exception:
                pass

            try:
                image = data.get("image")
                if isinstance(image, list):
                    image = image[0] if image else None
                if image:
                    profile["photo_url_full"] = image.split("?")[0]
            except Exception:
                pass

            try:
                geo = data.get("geo", {})
                profile["latitude"] = geo.get("latitude")
                profile["longitude"] = geo.get("longitude")
            except Exception:
                pass

            try:
                if data.get("telephone"):
                    profile["phone"] = data["telephone"]
                if data.get("faxNumber"):
                    profile["fax"] = data["faxNumber"]
                if data.get("email"):
                    profile["email"] = data["email"]
            except Exception:
                pass

            try:
                hours_specs = data.get("openingHoursSpecification", [])
                if hours_specs:
                    hours = {}
                    for spec in hours_specs:
                        day = spec.get("dayOfWeek", "")
                        if "/" in day:
                            day = day.split("/")[-1]
                        opens = spec.get("opens", "")[:5]
                        closes = spec.get("closes", "")[:5]
                        if day:
                            entry = (
                                f"{opens}–{closes}" if opens and closes else "closed"
                            )
                            if day in hours:
                                hours[day] += f", {entry}"
                            else:
                                hours[day] = entry
                    profile["opening_hours"] = hours
            except Exception:
                pass

    except Exception as e:
        print(f"  [!] JSON-LD error ({doctor.get('name', '?')}): {e}")

    doctor.update(profile)
    return doctor


def save_to_json(doctors, filename):
    """Save the list of doctors to a JSON file."""
    if not doctors:
        print("[!] No data to save.")
        return
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(doctors, f, ensure_ascii=False, indent=4)
    print(f"\n[SAVE] Saved {len(doctors)} doctors to {filename}")


async def main():
    """Collect doctors from search pages then enrich each with full profile data."""
    connector = aiohttp.TCPConnector(limit=CONCURRENCY)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        print("=== STAGE 1: Collecting basic data from search pages ===\n")
        all_doctors = []
        page = 1

        while len(all_doctors) < TARGET_COUNT:
            print(f"--- Page {page} (collected: {len(all_doctors)}/{TARGET_COUNT}) ---")
            doctors = await parse_page(session, page)

            if not doctors:
                print(f"[!] Page {page} is empty.")
                break

            all_doctors.extend(doctors)
            page += 1
            await asyncio.sleep(PAGE_DELAY)

        all_doctors = all_doctors[:TARGET_COUNT]
        print(f"\n[OK] Basic data collected: {len(all_doctors)} doctors")

        print(f"\n=== STAGE 2: Fetching profiles (concurrency: {CONCURRENCY}) ===\n")
        semaphore = asyncio.Semaphore(CONCURRENCY)

        tasks = [fetch_profile(session, semaphore, doc) for doc in all_doctors]
        results = []
        for coro in asyncio.as_completed(tasks):
            doc = await coro
            results.append(doc)
            print(f"  [{len(results)}/{len(all_doctors)}] {doc.get('name', '?')}")

    url_to_doc = {d["profile_url"]: d for d in results}
    ordered = [url_to_doc.get(d["profile_url"], d) for d in all_doctors]

    if ordered:
        print(f"\n  [INFO] First doctor example:")
        for key, value in ordered[0].items():
            print(f"     {key}: {value}")
        print()

    save_to_json(ordered, OUTPUT_FILE)
    print(f"\n[DONE] Done! Collected {len(ordered)} doctors.")
    print(f"[FILE] File: {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
