# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DocFinderAT is an async web scraper that collects all doctors from docfinder.at across all specialties and stores them in PostgreSQL + JSON. Coverage: all Austrian postal codes (1000–9999) × 32 specialties.

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
python modules/run.py

# Resume after interruption — just run again, completed specialties are skipped
python modules/run.py

# Start over — delete checkpoint first
del collect_checkpoint.json && python modules/run.py
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
collector.py: для кожного поштового індексу (1000–9999)
    → URL: /suche/{slug}/{postal_code}?page={n}
    → 10 індексів паралельно, пагінація до кінця
    → порожні індекси (~7000) пропускаються після 1 запиту
    ↓
parser.py: fetch_profile() — збагачення профілів
    → 20 профілів паралельно
    → JSON-LD structured data: phone, email, hours, coordinates
    ↓
saver.py: зберігає в PostgreSQL (update_or_create) + JSON
    ↓
checkpoint.py: прогрес по спеціальностях
```

### modules/ Structure

```
modules/
  config.py      — SPECIALTIES, POSTAL_CODES, константи
  parser.py      — extract_doctor() + fetch_profile()
  collector.py   — collect_specialty() через всі поштові індекси
  saver.py       — save_to_db() + save_to_json()
  checkpoint.py  — load/save прогресу
  run.py         — точка входу
  archive/       — старі скрипти (не використовуються)
```

### Django ORM in Standalone Scripts

`load_django.py` bootstraps Django ORM — imported first in `run.py`. Django project lives at `docfinderat_project/docfinderat_project/` (double-nested). Only `saver.py` imports Django models.

### Key Models (`docfinderat_project/parser_app/models.py`)

- **Doctor**: `profile_url` unique key, `opening_hours` JSONField, `db_table='doctors'`
- **DoctorGallery**: FK to Doctor (cascade), `db_table='doctor_gallery'`

## Configuration (`modules/config.py`)

- `POSTAL_CODES` — `range(1000, 10000)` — auto-generated
- `SPECIALTIES` — list of `(slug, display)` tuples
- `POSTAL_CONCURRENCY = 10`, `PROFILE_CONCURRENCY = 20`, `PAGE_DELAY = 0.5`
- Checkpoint: `collect_checkpoint.json` (project root)
- JSON output: `json/doctors.json`

All DB credentials in `.env` (not committed), read via `python-decouple`.
