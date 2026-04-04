import sys
import os
import django

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DJANGO_PROJECT = os.path.join(BASE_DIR, "..", "docfinderat_project")

if DJANGO_PROJECT not in sys.path:
    sys.path.insert(0, DJANGO_PROJECT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docfinderat_project.settings")
django.setup()
