import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import load_django  # noqa: F401  initializes Django ORM

import asyncio
import aiohttp
import json
import importlib.util
from bs4 import BeautifulSoup
from decimal import Decimal, InvalidOperation

from asgiref.sync import sync_to_async
from parser_app.models import Doctor, DoctorGallery

_spec = importlib.util.spec_from_file_location(
    "get_page", os.path.join(os.path.dirname(__file__), "1_get_page.py")
)
_get_page = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_get_page)

collect_all = _get_page.collect_all
HEADERS = _get_page.HEADERS
CONCURRENCY = _get_page.CONCURRENCY

sys.stdout.reconfigure(encoding="utf-8")


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


def save_to_db(doctors):
    """Save doctors to PostgreSQL via Django ORM using update_or_create."""
    Doctor.objects.all().delete()
    saved = 0
    for d in doctors:
        d = d.copy()
        gallery_urls = d.pop("gallery", None)

        try:
            reviews = int(d.pop("reviews", None) or 0) or None
        except (ValueError, TypeError):
            reviews = None

        lat_val = d.pop("latitude", None)
        try:
            latitude = Decimal(str(lat_val)) if lat_val else None
        except InvalidOperation:
            latitude = None

        lon_val = d.pop("longitude", None)
        try:
            longitude = Decimal(str(lon_val)) if lon_val else None
        except InvalidOperation:
            longitude = None

        profile_url = d.pop("profile_url", None)
        if not profile_url:
            continue

        doctor_obj, created = Doctor.objects.get_or_create(
            profile_url=profile_url,
            defaults={
                **d,
                "reviews": reviews,
                "latitude": latitude,
                "longitude": longitude,
            },
        )

        if created and gallery_urls:
            for url in gallery_urls:
                DoctorGallery.objects.create(doctor=doctor_obj, photo_url=url)

        saved += 1

    print(f"\n[SAVE] Saved {saved} doctors to database.")


async def main():
    """Collect doctors from search pages, enrich with profile data, save to DB."""
    connector = aiohttp.TCPConnector(limit=CONCURRENCY)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        print("=== STAGE 1: Collecting basic data from search pages ===\n")
        all_doctors = await collect_all(session)
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

    seen = set()
    unique = []
    for d in all_doctors:
        url = d["profile_url"]
        if url and url not in seen:
            seen.add(url)
            unique.append(url_to_doc.get(url, d))

    print(f"[OK] Unique doctors after dedup: {len(unique)}")

    if unique:
        print(f"\n  [INFO] First doctor example:")
        for key, value in unique[0].items():
            print(f"     {key}: {value}")
        print()

    await sync_to_async(save_to_db)(unique)
    print(f"\n[DONE] Done! Collected {len(unique)} unique doctors.")


if __name__ == "__main__":
    asyncio.run(main())
