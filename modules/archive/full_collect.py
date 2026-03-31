"""
full_collect.py — повний збір ВСІХ лікарів з docfinder.at по всіх спеціальностях.

Особливості:
  - Обходить усі спеціальності зі списку SPECIALTIES
  - Для кожної спеціальності обходить ~80 міст Австрії (паралельно)
  - Збирає всі сторінки без ліміту (поки є результати)
  - Зберігає прогрес у full_collect_checkpoint.json (відновлення після зупинки)
  - Не видаляє існуючі дані в БД — використовує update_or_create

Запуск:
    python modules/full_collect.py

Відновлення після зупинки:
    Просто запустіть знову — завершені спеціальності будуть пропущені.

Щоб почати з нуля — видаліть full_collect_checkpoint.json
"""

import sys
import os
import json
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import load_django  # noqa: F401

from asgiref.sync import sync_to_async
from parser_app.models import Doctor, DoctorGallery

sys.stdout.reconfigure(encoding="utf-8")

# ─── Налаштування ─────────────────────────────────────────────────────────────

CITY_CONCURRENCY = 5  # скільки міст обробляти паралельно
PROFILE_CONCURRENCY = 20  # скільки профілів завантажувати паралельно
PAGE_DELAY = 0.5  # секунд між сторінками одного міста

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
}

CHECKPOINT_FILE = os.path.join(
    os.path.dirname(__file__), "..", "full_collect_checkpoint.json"
)

# ─── Міста Австрії ─────────────────────────────────────────────────────────────
# Охоплює всі 9 федеральних земель (~80 міст)
CITIES = [
    # Wien
    "wien",
    # Niederösterreich
    "st-poelten",
    "wiener-neustadt",
    "krems",
    "klosterneuburg",
    "amstetten",
    "modling",
    "schwechat",
    "tulln",
    "stockerau",
    "mistelbach",
    "hollabrunn",
    "korneuburg",
    "neunkirchen",
    "perchtoldsdorf",
    "brunn-am-gebirge",
    "bad-voeslau",
    "traiskirchen",
    "waidhofen-an-der-ybbs",
    "zwettl",
    # Oberösterreich
    "linz",
    "wels",
    "steyr",
    "traun",
    "leonding",
    "voecklabruck",
    "braunau",
    "bad-ischl",
    "gmunden",
    "ried",
    "freistadt",
    "ansfelden",
    "enns",
    "marchtrenk",
    "perg",
    "grieskirchen",
    "schaerding",
    "kirchdorf",
    "rohrbach",
    # Steiermark
    "graz",
    "leoben",
    "kapfenberg",
    "bruck-an-der-mur",
    "knittelfeld",
    "voitsberg",
    "deutschlandsberg",
    "fuerstenfeld",
    "judenburg",
    "feldbach",
    "gleisdorf",
    "weiz",
    "leibnitz",
    "murau",
    "liezen",
    "bad-aussee",
    "radkersburg",
    # Tirol
    "innsbruck",
    "kufstein",
    "telfs",
    "hall-in-tirol",
    "schwaz",
    "imst",
    "reutte",
    "lienz",
    "woergl",
    "kitzbuhel",
    "landeck",
    "zell-am-ziller",
    "jenbach",
    # Kärnten
    "klagenfurt",
    "villach",
    "wolfsberg",
    "st-veit-an-der-glan",
    "spittal-an-der-drau",
    "feldkirchen-in-kaernten",
    "hermagor",
    "voelkermarkt",
    "althofen",
    "friesach",
    # Salzburg
    "salzburg",
    "hallein",
    "st-johann-im-pongau",
    "tamsweg",
    "zell-am-see",
    "bischofshofen",
    "saalfelden",
    # Vorarlberg
    "dornbirn",
    "feldkirch",
    "bregenz",
    "bludenz",
    "hohenems",
    "lustenau",
    "rankweil",
    "hard",
    "lauterach",
    "wolfurt",
    # Burgenland
    "eisenstadt",
    "oberwart",
    "neusiedl-am-see",
    "guessing",
    "jennersdorf",
    "mattersburg",
    "rust",
    "pinkafeld",
]

# ─── Спеціальності ─────────────────────────────────────────────────────────────
# Формат: (slug_в_URL, назва_для_originalWhat)
SPECIALTIES = [
    ("praktischer-arzt", "Praktischer Arzt"),
    ("zahnarzt", "Zahnarzt"),
    ("hautarzt", "Hautarzt"),
    ("frauenarzt", "Frauenarzt"),
    ("orthopaede", "Orthopäde"),
    ("augenarzt", "Augenarzt"),
    ("allgemeinmediziner", "Allgemeinmediziner"),
    ("internist", "Internist"),
    ("kinderarzt", "Kinderarzt"),
    ("hno-arzt", "HNO-Arzt"),
    ("neurologe", "Neurologe"),
    ("psychiater", "Psychiater"),
    ("urologe", "Urologe"),
    ("kardiologe", "Kardiologe"),
    ("chirurg", "Chirurg"),
    ("radiologe", "Radiologe"),
    ("gastroenterologe", "Gastroenterologe"),
    ("pneumologe", "Pneumologe"),
    ("rheumatologe", "Rheumatologe"),
    ("onkologe", "Onkologe"),
    ("endokrinologe", "Endokrinologe"),
    ("nephrologe", "Nephrologe"),
    ("anasthesist", "Anästhesist"),
    ("sportarzt", "Sportarzt"),
    ("arbeitsmediziner", "Arbeitsmediziner"),
    ("psychologe", "Psychologe"),
    ("physiotherapeut", "Physiotherapeut"),
    ("zahntechniker", "Zahntechniker"),
    ("logopade", "Logopäde"),
    ("ergoterapeut", "Ergotherapeut"),
    ("diatolog", "Diätologe"),
    ("institute", "Primärversorgungseinheiten"),
]

# ─── Checkpoint ───────────────────────────────────────────────────────────────


def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, encoding="utf-8") as f:
            data = json.load(f)
        done = set(data.get("done", []))
        total = data.get("total_saved", 0)
        print(
            f"[CHECKPOINT] Знайдено checkpoint: {len(done)} спеціальностей завершено, {total} лікарів збережено."
        )
        return done, total
    return set(), 0


def save_checkpoint(done_slugs, total_saved):
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"done": list(done_slugs), "total_saved": total_saved},
            f,
            ensure_ascii=False,
            indent=2,
        )


# ─── Парсинг карток ───────────────────────────────────────────────────────────


def extract_doctor(card):
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
        services = [
            t.text.strip()
            for t in tags
            if t.text.strip() and t.text.strip() != "Mehr..."
        ]
        doctor["services"] = "; ".join(services)
    except Exception:
        doctor["services"] = None

    try:
        img_tag = card.find("img", style="opacity: 1;")
        doctor["photo_url"] = (
            img_tag["src"].split("?")[0] if img_tag and img_tag.get("src") else None
        )
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
            doctor["appointment_url"] = (
                appt_link["href"] if appt_link and appt_link.get("href") else None
            )
        else:
            doctor["appointment_url"] = None
    except Exception:
        doctor["appointment_url"] = None

    return doctor


# ─── Збір по місту ────────────────────────────────────────────────────────────


async def collect_city_pages(session, city_sem, slug, display, city):
    """
    Збирає всі сторінки для одного міста + спеціальності.
    Повертає список лікарів цього міста.
    """
    doctors = []
    seen_urls = set()
    page = 1

    async with city_sem:
        while True:
            url = (
                f"https://www.docfinder.at/suche/{slug}/{city}"
                f"?whatType=search_group&userSubmitted=1"
                f"&originalWhat={quote(display)}&page={page}"
            )

            try:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    resp.raise_for_status()
                    html = await resp.text()
            except Exception as e:
                print(f"  [!] {display}/{city} стор.{page}: {e}")
                break

            soup = BeautifulSoup(html, "lxml")
            cards = soup.find_all("div", class_="card search-result")

            if not cards:
                break

            added = 0
            for card in cards:
                doc = extract_doctor(card)
                url_val = doc.get("profile_url")
                if url_val and url_val not in seen_urls:
                    seen_urls.add(url_val)
                    doctors.append(doc)
                    added += 1

            print(
                f"  [>] {display}/{city} стор.{page}: +{added} (місто: {len(doctors)})"
            )

            if added == 0:
                break

            page += 1
            await asyncio.sleep(PAGE_DELAY)

    return doctors


async def collect_specialty(session, slug, display):
    """
    Збирає всіх лікарів по спеціальності через всі міста паралельно.
    Повертає дедублікований список.
    """
    city_sem = asyncio.Semaphore(CITY_CONCURRENCY)
    tasks = [
        collect_city_pages(session, city_sem, slug, display, city) for city in CITIES
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    seen_urls = set()
    all_doctors = []
    for city_result in results:
        if isinstance(city_result, Exception):
            continue
        for doc in city_result:
            url = doc.get("profile_url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_doctors.append(doc)

    return all_doctors


# ─── Збагачення профілів ──────────────────────────────────────────────────────


async def fetch_profile(session, semaphore, doctor):
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
            ) as resp:
                resp.raise_for_status()
                html = await resp.text()
        except Exception as e:
            print(f"  [!] Профіль {doctor.get('name', '?')}: {e}")
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
            addr = data.get("address", {})
            profile["address_full"] = addr.get("streetAddress")
            profile["zip_code"] = addr.get("postalCode")
            profile["city"] = addr.get("addressLocality")
            profile["website"] = data.get("url")
            profile["description"] = data.get("description")

            image = data.get("image")
            if isinstance(image, list):
                image = image[0] if image else None
            if image:
                profile["photo_url_full"] = image.split("?")[0]

            geo = data.get("geo", {})
            profile["latitude"] = geo.get("latitude")
            profile["longitude"] = geo.get("longitude")

            if data.get("telephone"):
                profile["phone"] = data["telephone"]
            if data.get("faxNumber"):
                profile["fax"] = data["faxNumber"]
            if data.get("email"):
                profile["email"] = data["email"]

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
                        entry = f"{opens}–{closes}" if opens and closes else "closed"
                        hours[day] = (
                            hours[day] + f", {entry}" if day in hours else entry
                        )
                profile["opening_hours"] = hours

    except Exception as e:
        print(f"  [!] JSON-LD ({doctor.get('name', '?')}): {e}")

    doctor.update(profile)
    return doctor


# ─── Збереження в БД ──────────────────────────────────────────────────────────


def save_batch_to_db(doctors):
    """Зберігає лікарів через update_or_create. Не видаляє існуючі записи."""
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

        doctor_obj, created = Doctor.objects.update_or_create(
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
                DoctorGallery.objects.get_or_create(doctor=doctor_obj, photo_url=url)

        saved += 1

    return saved


# ─── Головна логіка ───────────────────────────────────────────────────────────


async def main():
    done_slugs, total_saved = load_checkpoint()

    pending = [
        (slug, display) for slug, display in SPECIALTIES if slug not in done_slugs
    ]

    if not pending:
        print(
            "[DONE] Усі спеціальності вже оброблені. Видаліть full_collect_checkpoint.json щоб почати знову."
        )
        return

    print(f"\n[START] Спеціальностей до обробки: {len(pending)} з {len(SPECIALTIES)}")
    print(f"[START] Міст для обходу: {len(CITIES)}")
    print(
        f"[START] Паралельність міст: {CITY_CONCURRENCY}, профілів: {PROFILE_CONCURRENCY}"
    )
    print(f"[INFO]  Вже збережено лікарів: {total_saved}\n")

    connector = aiohttp.TCPConnector(limit=max(CITY_CONCURRENCY, PROFILE_CONCURRENCY))
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        for idx, (slug, display) in enumerate(pending, 1):
            print(f"\n{'=' * 60}")
            print(f"[{idx}/{len(pending)}] {display}  (slug: {slug})")
            print(f"{'=' * 60}")

            # Етап 1: збір по всіх містах паралельно
            print(
                f"[STAGE 1] Збираємо список з {len(CITIES)} міст (паралельно {CITY_CONCURRENCY})..."
            )
            doctors = await collect_specialty(session, slug, display)
            print(f"\n[OK] {display}: зібрано {len(doctors)} унікальних лікарів")

            if not doctors:
                print(f"[SKIP] {display}: лікарів не знайдено, пропускаємо.")
                done_slugs.add(slug)
                save_checkpoint(done_slugs, total_saved)
                continue

            # Етап 2: збагачення профілів
            print(
                f"\n[STAGE 2] Завантажуємо профілі (паралельно {PROFILE_CONCURRENCY})..."
            )
            semaphore = asyncio.Semaphore(PROFILE_CONCURRENCY)
            tasks = [fetch_profile(session, semaphore, doc) for doc in doctors]
            enriched = []
            for coro in asyncio.as_completed(tasks):
                doc = await coro
                enriched.append(doc)
                if len(enriched) % 50 == 0 or len(enriched) == len(doctors):
                    print(f"  [{len(enriched)}/{len(doctors)}] профілів оброблено...")

            # Дедублікація після збагачення
            seen = set()
            unique = []
            for d in enriched:
                url = d.get("profile_url")
                if url and url not in seen:
                    seen.add(url)
                    unique.append(d)

            # Етап 3: збереження в БД
            print(f"\n[STAGE 3] Зберігаємо {len(unique)} лікарів у БД...")
            batch_saved = await sync_to_async(save_batch_to_db)(unique)
            total_saved += batch_saved
            print(
                f"[OK] {display}: збережено {batch_saved}. Всього в БД: {total_saved}"
            )

            done_slugs.add(slug)
            save_checkpoint(done_slugs, total_saved)
            print(
                f"[CHECKPOINT] {len(done_slugs)}/{len(SPECIALTIES)} спеціальностей завершено."
            )

    print(f"\n{'=' * 60}")
    print(f"[DONE] Збір завершено!")
    print(f"[DONE] Всього збережено: {total_saved} лікарів")
    print(f"[DONE] Оброблено спеціальностей: {len(done_slugs)}/{len(SPECIALTIES)}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
