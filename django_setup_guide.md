# Інструкція: Створення Django проекту з PostgreSQL для парсера

> **Шаблонні назви** — замінити перед початком:
>
> | Плейсхолдер | Що вставити | Приклад |
> |-------------|-------------|---------|
> | `<project_name>` | домен без крапок + `_project` | `braincomua_project` |
> | `<db_name>` | `<project_name>` + `_db` | `braincomua_db` |
> | `<db_user>` | `<project_name>` + `_user` | `braincomua_user` |
> | `<db_password>` | довільний пароль | `mypassword123` |
> | `<site_url>` | базовий URL сайту | `https://brain.com.ua` |

---

## Фінальна структура проекту

```
Parsing_Project/                       ← корінь (робоча папка)
├── files/                             ← файли (фото, документи тощо)
├── <project_name>-env/                ← віртуальне середовище
├── <project_name>/                    ← Django проект
│   ├── manage.py
│   ├── <project_name>/                ← налаштування (settings, urls, wsgi)
│   │   ├── __init__.py
│   │   ├── settings.py
│   │   ├── urls.py
│   │   └── wsgi.py
│   └── parser_app/                    ← додаток парсера
│       ├── models.py
│       ├── admin.py
│       └── ...
├── modules/                           ← скрипти парсера (ПОЗА Django проектом)
│   ├── load_django.py
│   ├── 1_get_listings.py
│   └── 2_get_info.py
└── results/                           ← результати (CSV, дампи БД)
```

> Папка `modules/` знаходиться на одному рівні з `<project_name>/`, НЕ всередині неї.

---

## КРОК 1 — Створення віртуального середовища

```bash
cd C:\Users\<user>\...\Parsing_Project

python -m venv <project_name>-env
```

Активувати (Windows):
```bash
<project_name>-env\Scripts\activate
```

---

## КРОК 2 — Встановлення залежностей

```bash
pip install django psycopg2-binary requests beautifulsoup4 lxml
```

Перевірити:
```bash
python -m django --version
```

---

## КРОК 3 — Створення Django проекту

Знаходячись у `Parsing_Project/`:
```bash
django-admin startproject docfinderat_project
```

Це створить папку `<project_name>/` з `manage.py` всередині.

Перейти всередину і створити додаток:
```bash
cd <project_name>
python manage.py startapp parser_app
```

---

## КРОК 4 — Створення бази даних у PostgreSQL

Відкрити pgAdmin або psql і виконати:
```sql
CREATE DATABASE <db_name>;
CREATE USER <db_user> WITH PASSWORD '<db_password>';
GRANT ALL PRIVILEGES ON DATABASE <db_name> TO <db_user>;
```

---

## КРОК 5 — Підключення PostgreSQL у settings.py

Файл: `<project_name>/<project_name>/settings.py`

Знайти `DATABASES` і замінити:
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': '<db_name>',
        'USER': '<db_user>',
        'PASSWORD': '<db_password>',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
```

Додати `parser_app` до `INSTALLED_APPS`:
```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'parser_app',              # ← додати
]
```

---

## КРОК 6 — Створення моделі

Файл: `<project_name>/parser_app/models.py`
```python
from django.db import models


class Product(models.Model):
    name = models.CharField(max_length=500)
    price = models.CharField(max_length=100)

    def __str__(self):
        return self.name
```

---

## КРОК 7 — Міграції

```bash
# Знаходитись в <project_name>/ (де manage.py)
python manage.py makemigrations
python manage.py migrate
```

---

## КРОК 8 — Створення папки modules та load_django.py

Повернутись в корінь `Parsing_Project/`:
```bash
cd ..
mkdir modules
mkdir results
mkdir files
```

Створити файл `modules/load_django.py`:
```python
import sys
import os
import django

# Шлях до папки Django проекту (де лежить manage.py)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '<project_name>'))

# Назва модуля налаштувань (назва внутрішньої папки з settings.py)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', '<project_name>.settings')

django.setup()
```

> У кожному скрипті в `modules/` додавати на початку:
> ```python
> from load_django import *
> from parser_app.models import *
> ```

---

## КРОК 9 — Тестовий скрипт: запис у БД

Файл `modules/1_write_to_db.py`:
```python
"""
Тестовий скрипт — записує товар у базу даних
"""
from load_django import *
from parser_app.models import Product


product = Product(name="Тестовий продукт", price="1000")
product.save()

print("Записано успішно!")
print(f"ID: {product.id} | Назва: {product.name} | Ціна: {product.price}")
```

Запустити з папки `modules/`:
```bash
cd C:\Users\<user>\...\Parsing_Project\modules
python 1_write_to_db.py
```

---

## КРОК 10 — Тестовий скрипт: читання з БД

Файл `modules/2_read_from_db.py`:
```python
"""
Тестовий скрипт — отримує всі товари з бази даних і виводить їх
"""
from load_django import *
from parser_app.models import Product


products = Product.objects.all()

for product in products:
    print(f"ID: {product.id} | Назва: {product.name} | Ціна: {product.price}")
    print("-" * 50)
```

Запустити:
```bash
python 2_read_from_db.py
```

---

## КРОК 11 — Підключення парсера до Django (збереження в БД)

Коли тестові скрипти працюють, підключаємо реальний парсинг.

**Було** (`parsing_level_3.py`):
```python
import requests
from bs4 import BeautifulSoup
import time

# ... (весь код парсера без змін)

for card in cards:
    slug = card.get("data-slug")
    if slug:
        full_url = f"<site_url>/{slug}.html"
        product = parse_product(full_url)
        all_products_data.append(product)   # ← просто додає в список
        time.sleep(0.3)

for i in all_products_data:
    print(i)
    print("-" * 50)
```

**Стало** — додати 2 рядки зверху і замінити append на запис у БД:
```python
from load_django import *                   # ← додати рядок 1
from parser_app.models import Product       # ← додати рядок 2

import requests
from bs4 import BeautifulSoup
import time

# ... (весь код парсера без змін)

for card in cards:
    slug = card.get("data-slug")
    if slug:
        full_url = f"<site_url>/{slug}.html"
        product = parse_product(full_url)

        if product.get("name") and product.get("price"):   # ← замість append
            Product.objects.create(
                name=product["name"],
                price=product["price"],
            )
            print(f"Збережено: {product['name']} | {product['price']}")

        time.sleep(0.3)
```

> Перевірка `if product.get("name") and product.get("price")` захищає від збереження порожніх `{}` у БД.

### Як уникнути дублювання

Замість `Product.objects.create(...)` використовувати `get_or_create` — шукає запис за `name`, якщо не знайшов — створює:

```python
if product.get("name") and product.get("price"):
    obj, created = Product.objects.get_or_create(
        name=product["name"],
        defaults={"price": product["price"]},
    )
    if created:
        print(f"Збережено: {obj.name} | {obj.price}")
    else:
        print(f"Вже існує: {obj.name}")
```

- `created=True` — запис новий, був доданий в БД
- `created=False` — запис вже існував, нічого не змінилось

---

## Швидка інструкція (5-10 хвилин)

```bash
# 1. Перейти в корінь проекту
cd C:\Users\<user>\...\Parsing_Project

# 2. Створити та активувати venv
python -m venv <project_name>-env
<project_name>-env\Scripts\activate

# 3. Встановити залежності
pip install django psycopg2-binary requests beautifulsoup4 lxml

# 4. Створити Django проект
django-admin startproject <project_name>
cd <project_name>
python manage.py startapp parser_app

# 5. Створити БД у PostgreSQL (pgAdmin або psql)
# CREATE DATABASE <db_name>;
# CREATE USER <db_user> WITH PASSWORD '<db_password>';
# GRANT ALL PRIVILEGES ON DATABASE <db_name> TO <db_user>;

# 6. Відредагувати settings.py (DATABASES + INSTALLED_APPS)

# 7. Написати модель в parser_app/models.py

# 8. Міграції
python manage.py makemigrations
python manage.py migrate

# 9. Створити папки і файли
cd ..
mkdir modules results files
# Створити modules/load_django.py

# 10. Запустити тестові скрипти
cd modules
python 1_write_to_db.py
python 2_read_from_db.py
```

---

## Правила іменування

| Що | Правило | Приклад |
|----|---------|---------|
| Папка проекту | домен без крапок + `_project` | `braincomua_project` |
| Віртуальне середовище | домен без крапок + `-env` | `braincomua_project-env` |
| Додаток | завжди `parser_app` | `parser_app` |
| БД | назва проекту + `_db` | `braincomua_db` |
| Користувач БД | назва проекту + `_user` | `braincomua_user` |
| Скрипти в modules | цифра + назва дії | `1_get_listings.py` |
| Коментар у файлі | потрійні лапки зверху | `""" Що робить скрипт """` |
| Результати | зберігати в `results/` | `results/products.csv` | План: Розбивка парсера на модулі + Django ORM збереження                                                                                      │
   