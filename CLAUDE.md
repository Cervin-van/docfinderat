# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DocFinderAT is an async web scraper that collects all doctors from docfinder.at across all specialties and stores them in PostgreSQL + JSON. Coverage: all Austrian postal codes (1000–9999) × 62 specialties.

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure .env with PostgreSQL credentials (DB_NAME=past_doc, DB_USER=postgres)

# Run Django migrations
cd docfinderat_project && python manage.py migrate && cd ..
```

## Running the Scraper

```bash
# Full collection — all specialties, all postal codes
python modules/3_collect_all_doctors.py

# Single specialty
python modules/3_collect_all_doctors.py --slug zahnarzt

# Resume after interruption — just run again, completed specialties are skipped
python modules/3_collect_all_doctors.py

# Start over — delete checkpoint first
del collect_checkpoint.json && python modules/3_collect_all_doctors.py
```

## Django Admin

```bash
cd docfinderat_project && python manage.py runserver
# http://127.0.0.1:8000/admin/
```

## Architecture

### Scraping Pipeline

```
docfinder.at
    ↓
3_collect_all_doctors.py: collect_specialty()
    → iterates all postal codes (1000–9999) with POSTAL_CONCURRENCY=50
    → calls collect_postal_code() per code
    ↓
2_paginate_postal.py: collect_postal_code()
    → URL: /suche/{slug}/{postal_code}?page={n}
    → paginates up to MAX_PAGES=50, stops on empty page or all-duplicate cards
    → calls extract_doctor() per card
    ↓
1_parse_page.py: extract_doctor() + fetch_profile()
    → extract_doctor(): name, profile_url, rating, reviews, specialty, address,
      services, photo_url, gallery, appointment_url from search card HTML
    → fetch_profile(): phone, fax, email, website, description, address_full,
      zip_code, city, opening_hours, lat/lon from profile page JSON-LD
    ↓
3_collect_all_doctors.py: enrich() + save_to_db() + save_to_json()
    → PROFILE_CONCURRENCY=30 parallel profile fetches
    → batches of 100 doctors enriched + saved at a time
    → PostgreSQL via Django ORM (update_or_create on profile_url)
    → JSON: json/{slug}.json per specialty, json/_stats.json totals
    ↓
checkpoint: collect_checkpoint.json — tracks completed specialties
```

### modules/ File Structure

```
modules/
  1_parse_page.py          — extract_doctor() + fetch_profile()
  2_paginate_postal.py     — collect_postal_code() with pagination logic
  3_collect_all_doctors.py — entry point: collect_specialty(), enrich(),
                             save_to_db(), save_to_json(), checkpoint I/O
  config.py                — SPECIALTIES, POSTAL_CODES, all constants
  load_django.py           — bootstraps Django ORM for standalone scripts
  test_scraper.py          — tests
```

### JSON Output Structure

```
json/
  data/         — per-specialty JSON files: {slug}.json + _stats.json
  checkpoint/   — collect_checkpoint.json (tracks completed specialties)
```

### Django ORM in Standalone Scripts

`modules/load_django.py` bootstraps Django ORM — imported first in `3_collect_all_doctors.py`. Django project lives at `docfinderat_project/docfinderat_project/` (double-nested). Only `3_collect_all_doctors.py` imports Django models.

### Key Models (`docfinderat_project/parser_app/models.py`)

- **Doctor**: `profile_url` unique key, `opening_hours` JSONField, `db_table='doctors'`
- **DoctorGallery**: FK to Doctor (cascade), `db_table='doctor_gallery'`

## Configuration (`modules/config.py`)

- `POSTAL_CODES` — `range(1000, 10000)` as strings
- `SPECIALTIES` — 62 `(slug, display)` tuples
- `POSTAL_CONCURRENCY = 50`, `PROFILE_CONCURRENCY = 30`, `PAGE_DELAY = 0.2`, `MAX_PAGES = 50`
- `REQUEST_TIMEOUT = 20`
- Checkpoint: `json/checkpoint/collect_checkpoint.json`
- JSON output: `json/data/{slug}.json` per specialty, `json/data/_stats.json` for aggregate totals

All DB credentials in `.env` (not committed), read via `python-decouple`.
