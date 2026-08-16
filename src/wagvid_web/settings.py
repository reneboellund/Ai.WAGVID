import os
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parents[2]
SECRET_KEY = os.environ.get("WAGVID_SECRET_KEY", "unsafe-development-only")
DEBUG = os.environ.get("WAGVID_DEBUG", "1") == "1"
ALLOWED_HOSTS = [item for item in os.environ.get("WAGVID_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if item]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "wagvid_app",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "wagvid_web.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "wagvid_web.wsgi.application"
ASGI_APPLICATION = "wagvid_web.asgi.application"
database_url = os.environ.get("WAGVID_DATABASE_URL")
if database_url:
    parsed_database = urlparse(database_url)
    if parsed_database.scheme not in {"postgres", "postgresql"}:
        raise ValueError("WAGVID_DATABASE_URL must be a PostgreSQL URL")
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed_database.path.lstrip("/"),
        "USER": parsed_database.username,
        "PASSWORD": parsed_database.password,
        "HOST": parsed_database.hostname,
        "PORT": parsed_database.port or 5432,
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
AUTH_PASSWORD_VALIDATORS = [] if DEBUG else [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "da"
TIME_ZONE = os.environ.get("WAGVID_TIME_ZONE", "Europe/Copenhagen")
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
WAGVID_OBJECT_ROOT = Path(os.environ.get("WAGVID_OBJECT_ROOT", BASE_DIR / "media"))
WAGVID_MIN_FREE_BYTES = int(os.environ.get("WAGVID_MIN_FREE_BYTES", str(5 * 1024**3)))
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

if not DEBUG:
    if SECRET_KEY == "unsafe-development-only":
        raise ValueError("WAGVID_SECRET_KEY is required outside development")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.environ.get("WAGVID_SECURE_SSL_REDIRECT", "1") == "1"
    SECURE_HSTS_SECONDS = int(os.environ.get("WAGVID_HSTS_SECONDS", "3600"))
