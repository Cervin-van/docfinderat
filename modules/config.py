"""
config.py — всі константи та налаштування парсера.
"""

import os

# ─── HTTP ─────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
}

# ─── Швидкість збору ──────────────────────────────────────────────────────────

# Максимум паралельних HTTP-запитів при зборі по поштових індексах
POSTAL_CONCURRENCY = 50

# Скільки профілів лікарів завантажувати паралельно
PROFILE_CONCURRENCY = 30

# Затримка між сторінками одного поштового індексу (секунди)
PAGE_DELAY = 0.2

# Таймаут на один HTTP-запит (секунди)
REQUEST_TIMEOUT = 20

# ─── Поштові індекси ──────────────────────────────────────────────────────────
POSTAL_CODES = [str(i) for i in range(1000, 10000)]

# ─── Пагінація ────────────────────────────────────────────────────────────────
MAX_PAGES = 50

# ─── Спеціальності ────────────────────────────────────────────────────────────
# Формат: (slug у URL, відображувана назва)
# Slug-и генеровані за правилом: малі літери, пробіли→дефіси, ä→ae, ö→oe, ü→ue, ß→ss
# Підтверджені slug-и позначені: # ✓
# Непідтверджені — перевірте через: python modules/verify_slugs.py
SPECIALTIES = [
    ("anaesthesist", "Anästhesiologe"),
    ("arbeitsmediziner", "Arbeitsmediziner"),
    ("chirurgische-elektrophysiologie", "Chirurgische Elektrophysiologie"),
    ("elektrotherapie", "Elektrotherapie"),
    ("embryologe", "Embryologe"),
    ("endokrinologe", "Endokrinologe"),
    ("fachärztin-fuer-allgemeinchirurgie", "Fachärztin für Allgemeinchirurgie"),
    ("frauenarzt", "Frauenarzt"),
    ("gefaesschirurg", "Gefäßchirurg"),
    ("geriater", "Geriater"),
    ("gerichtsmediziner", "Gerichtsmediziner"),
    ("hals-nasen-ohren-arzt", "Hals-, Nasen-, Ohren-Arzt"),
    ("hausarzt", "Hausarzt"),
    ("hautarzt", "Hautarzt"),
    ("hepatologe", "Hepatologe"),
    ("herzchirurg", "Herzchirurg"),
    ("immunbiologe", "Immunbiologe"),
    ("infektiologe", "Infektiologe"),
    ("intensivmediziner", "Intensivmediziner"),
    ("internist", "Internist"),
    ("internist-fuer-angiologie", "Internist für Angiologie"),
    ("jugendchirurgie", "Jugendchirurgie"),
    ("kardiologe", "Kardiologe"),
    ("kieferchirurg", "Kieferchirurg"),
    ("kinder-kardiologe", "Kinder Kardiologe"),
    ("kinder-und-jugendpsychiater", "Kinder- und Jugendpsychiater"),
    ("kinderarzt", "Kinderarzt"),
    ("labordiagnostiker", "Labordiagnostiker"),
    ("lungenarzt", "Lungenarzt"),
    ("medizinischer-biophysiker", "Medizinischer Biophysiker"),
    ("medizinischer-genetiker", "Medizinischer Genetiker"),
    ("medizinischer-leistungsphysiologe", "Medizinischer Leistungsphysiologe"),
    ("mikrobiologe", "Mikrobiologe"),
    ("neonatologe", "Neonatologe"),
    ("nephrologe", "Nephrologe"),
    ("neurochirurg", "Neurochirurg"),
    ("neurologe", "Neurologe"),
    ("neuropathologe", "Neuropathologe"),
    ("onkologe", "Onkologe"),
    ("orthopaede", "Orthopäde"),
    ("pathologe", "Pathologe"),
    ("pathophysiologe", "Pathophysiologe"),
    ("phoniater", "Phoniater"),
    ("physikalischer-mediziner", "Physikalischer Mediziner"),
    ("radiologe", "Radiologe"),
    ("rheumatologe", "Rheumatologe"),
    ("schmerzmediziner", "Schmerzmediziner"),
    ("schoenheitschirurg", "Schönheitschirurg"),
    ("sozialmediziner", "Sozialmediziner"),
    ("sportarzt", "Sportarzt"),
    ("strahlentherapeut", "Strahlentherapeut"),
    ("thoraxchirurg", "Thoraxchirurg"),
    ("toxikologe", "Toxikologe"),
    ("transfusionsmediziner", "Transfusionsmediziner"),
    ("traumatologe", "Traumatologe"),
    ("tropenmediziner", "Tropenmediziner"),
    ("unfallchirurg", "Unfallchirurg"),
    ("urologe", "Urologe"),
    ("virologe", "Virologe"),
    ("viszeralchirurg", "Viszeralchirurg"),
    ("zahnarzt", "Zahnarzt"),
    ("zytodiagnostiker", "Zytodiagnostiker"),
]

_ROOT = os.path.join(os.path.dirname(__file__), "..")

CHECKPOINT_FILE = os.path.join(_ROOT, "json", "checkpoint", "collect_checkpoint.json")
JSON_DIR = os.path.join(_ROOT, "json", "data")
