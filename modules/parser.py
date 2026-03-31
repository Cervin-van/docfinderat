"""
parser.py — парсинг HTML: картки пошукової видачі та профілі лікарів.
Не залежить від Django — лише BeautifulSoup + aiohttp.
"""

import json
import asyncio
import aiohttp
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT


def extract_doctor(card) -> dict:
    """Витягує базові дані лікаря з картки пошукової видачі."""
    doc = {}

    try:
        tag = card.find("p", class_="shave")
        doc["name"] = tag.text.strip() if tag else ""
    except Exception:
        doc["name"] = ""

    try:
        link = card.find("a", attrs={"aria-label": True})
        doc["profile_url"] = "https://www.docfinder.at" + link["href"]
    except Exception:
        doc["profile_url"] = None

    try:
        doc["rating"] = card.find("div", class_="stars")["title"]
    except Exception:
        doc["rating"] = None

    try:
        doc["reviews"] = card.find("span", class_="count").text.strip().strip("()")
    except Exception:
        doc["reviews"] = None

    try:
        tag = card.find("div", class_="professions")
        doc["specialty"] = tag.text.strip() if tag else ""
    except Exception:
        doc["specialty"] = None

    try:
        tag = card.find("div", class_="location-text")
        doc["address"] = tag.text.strip() if tag else ""
    except Exception:
        doc["address"] = None

    try:
        tags = card.find_all("a", class_="tag")
        services = [t.text.strip() for t in tags if t.text.strip() and t.text.strip() != "Mehr..."]
        doc["services"] = "; ".join(services)
    except Exception:
        doc["services"] = None

    try:
        img = card.find("img", style="opacity: 1;")
        doc["photo_url"] = img["src"].split("?")[0] if img and img.get("src") else None
    except Exception:
        doc["photo_url"] = None

    try:
        gallery_div = card.find("div", class_="gallery desktop hidden-md-down")
        gallery = []
        if gallery_div:
            for img in gallery_div.find_all("img"):
                src = img.get("data-src") or img.get("src")
                if src and not src.startswith("data:"):
                    gallery.append(src.split("?")[0])
        doc["gallery"] = gallery if gallery else None
    except Exception:
        doc["gallery"] = None

    try:
        appt = card.find("div", class_="book-appointment")
        if appt:
            a = appt.find("a")
            doc["appointment_url"] = a["href"] if a and a.get("href") else None
        else:
            doc["appointment_url"] = None
    except Exception:
        doc["appointment_url"] = None

    return doc


async def fetch_profile(session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, doctor: dict) -> dict:
    """
    Завантажує профільну сторінку лікаря і збагачує словник doctor
    полями: phone, fax, email, website, description, address_full,
    zip_code, city, opening_hours, latitude, longitude, photo_url_full.
    """
    empty = {
        "phone": None, "fax": None, "email": None, "website": None,
        "description": None, "address_full": None, "zip_code": None,
        "city": None, "opening_hours": None,
        "latitude": None, "longitude": None, "photo_url_full": None,
    }

    profile_url = doctor.get("profile_url")
    if not profile_url:
        doctor.update(empty)
        return doctor

    async with semaphore:
        try:
            async with session.get(
                profile_url,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                resp.raise_for_status()
                html = await resp.text()
        except Exception as e:
            print(f"  [!] Профіль {doctor.get('name', '?')}: {e}")
            doctor.update(empty)
            return doctor

    soup = BeautifulSoup(html, "lxml")
    profile = dict(empty)

    # Телефон / факс / email з посилань
    try:
        a = soup.select_one('a[href^="tel:"]')
        if a:
            profile["phone"] = a.get_text(strip=True)
    except Exception:
        pass

    try:
        a = soup.select_one('a[href^="fax:"]')
        if a:
            profile["fax"] = a.get_text(strip=True)
    except Exception:
        pass

    try:
        a = soup.select_one('a[href^="mailto:"]')
        if a:
            profile["email"] = a.get_text(strip=True)
    except Exception:
        pass

    # JSON-LD — основне джерело структурованих даних
    try:
        data = {}
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            if not script.string:
                continue
            parsed = json.loads(script.string)
            if "mainEntity" in parsed:
                data = parsed["mainEntity"]
                break

        if data:
            addr = data.get("address", {})
            profile["address_full"] = addr.get("streetAddress")
            profile["zip_code"]     = addr.get("postalCode")
            profile["city"]         = addr.get("addressLocality")
            profile["website"]      = data.get("url")
            profile["description"]  = data.get("description")

            # Фото
            image = data.get("image")
            if isinstance(image, list):
                image = image[0] if image else None
            if image:
                profile["photo_url_full"] = image.split("?")[0]

            # Координати
            geo = data.get("geo", {})
            profile["latitude"]  = geo.get("latitude")
            profile["longitude"] = geo.get("longitude")

            # Контакти з JSON-LD мають пріоритет над посиланнями
            if data.get("telephone"):
                profile["phone"] = data["telephone"]
            if data.get("faxNumber"):
                profile["fax"] = data["faxNumber"]
            if data.get("email"):
                profile["email"] = data["email"]

            # Години роботи
            specs = data.get("openingHoursSpecification", [])
            if specs:
                hours = {}
                for spec in specs:
                    day = spec.get("dayOfWeek", "")
                    if "/" in day:
                        day = day.split("/")[-1]
                    opens  = spec.get("opens", "")[:5]
                    closes = spec.get("closes", "")[:5]
                    if day:
                        entry = f"{opens}–{closes}" if opens and closes else "closed"
                        hours[day] = f"{hours[day]}, {entry}" if day in hours else entry
                profile["opening_hours"] = hours

    except Exception as e:
        print(f"  [!] JSON-LD ({doctor.get('name', '?')}): {e}")

    doctor.update(profile)
    return doctor
