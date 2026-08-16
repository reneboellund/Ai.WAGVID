# Local product-shell development

```powershell
py -3.12 -m pip install -e ".[dev]"
py -3.12 manage.py migrate
py -3.12 manage.py bootstrap_wagvid --username admin
py -3.12 manage.py changepassword admin
py -3.12 manage.py runserver
```

Open `http://127.0.0.1:8000/`. Health endpoints are `/health/` and `/ready/`; trusted maintenance
admin is `/admin/maintenance/`.

SQLite is intentionally limited to local development and tests. The first deployable on-prem stack
must use PostgreSQL, S3-compatible object storage and a durable worker backend. Never use the
development secret or debug mode outside a developer machine.

Quick validation:

```powershell
py -3.12 -m ruff check .
py -3.12 manage.py check
py -3.12 manage.py makemigrations --check
py -3.12 -m pytest -q
```
