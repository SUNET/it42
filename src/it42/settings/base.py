"""Settings shared by every zone: the core site, the org sites and the RO site.

Zone-specific settings live in ``core.py``, ``org.py`` and ``ro.py``. Every value that differs
between containers comes from the environment, so one image serves every zone.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from it42.common.saml_config import SAML_ATTRIBUTE_MAPPING

BASE_DIR = Path(__file__).resolve().parents[3]


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise ImproperlyConfigured(f"Environment variable {name} is required")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


DEBUG = env_bool("DJANGO_DEBUG")
# The fallback key only exists so that build steps such as collectstatic can import
# settings; containers always get a real key from their env file.
_BUILD_ONLY_KEY = "insecure-build-only-key"
SECRET_KEY = env("DJANGO_SECRET_KEY", _BUILD_ONLY_KEY)
if SECRET_KEY == _BUILD_ONLY_KEY and env_bool("IT42_RUNTIME"):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set at runtime")

SITE_HOST = env("SITE_HOST", "localhost")
SITE_URL = f"https://{SITE_HOST}"
SITE_NAME = env("SITE_NAME", "IT42")
THEME_COLOR = env("THEME_COLOR", "#0d6efd")

ALLOWED_HOSTS = [SITE_HOST, "localhost", "127.0.0.1"]
CSRF_TRUSTED_ORIGINS = [SITE_URL]

# Caddy terminates TLS and forwards Host and X-Forwarded-Proto.
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

BASE_INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "djangosaml2",
    "it42.common",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "djangosaml2.middleware.SamlSessionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

CONTEXT_PROCESSORS = [
    "django.template.context_processors.request",
    "django.contrib.auth.context_processors.auth",
    "django.contrib.messages.context_processors.messages",
    "it42.common.theme.theme",
]


# compose.dev.yaml bind-mounts templates/; TEMPLATES_LIVE drops the
# cached loader so an edited template shows on the next request, without a restart.
TEMPLATES_LIVE = env_bool("TEMPLATES_LIVE")


def templates(extra_context_processors: list[str]) -> list[dict[str, object]]:
    options: dict[str, object] = {
        "context_processors": [*CONTEXT_PROCESSORS, *extra_context_processors]
    }
    if TEMPLATES_LIVE:
        options["loaders"] = [
            "django.template.loaders.filesystem.Loader",
            "django.template.loaders.app_directories.Loader",
        ]
    return [
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [BASE_DIR / "templates"],
            "APP_DIRS": not TEMPLATES_LIVE,
            "OPTIONS": options,
        }
    ]


TEMPLATES = templates([])

WSGI_APPLICATION = "it42.wsgi.application"

if "POSTGRES_HOST" in os.environ:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": env("POSTGRES_HOST"),
            "PORT": env("POSTGRES_PORT", "5432"),
            "NAME": env("POSTGRES_DB"),
            "USER": env("POSTGRES_USER"),
            "PASSWORD": env("POSTGRES_PASSWORD"),
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    # Local development and the test suite use SQLite.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / f"dev-{env('APP_ROLE', 'core')}{env('ORG_SLUG', '')}.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Stockholm"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
# Local development mounts static/ over STATIC_ROOT. Read each request from disk
# and use unhashed URLs so edits do not require collectstatic or a container restart.
if env_bool("STATICFILES_LIVE"):
    STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
    WHITENOISE_AUTOREFRESH = True
    WHITENOISE_MAX_AGE = 0

MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))
MEDIA_URL = "/media/"
# Uploaded PDFs are limited to 5 MB; leave headroom for the multipart envelope.
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
MAX_PDF_BYTES = 5 * 1024 * 1024

LOGIN_URL = "/saml2/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/logged-out/"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "it42.common.saml.SubjectSaml2Backend",
]

# RabbitMQ: only workers set these (from env/<zone>-mq.env).
RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.environ.get("RABBITMQ_PORT", "5672"))
RABBITMQ_VHOST = os.environ.get("RABBITMQ_VHOST", "/it42")
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "")
RABBITMQ_PASSWORD = os.environ.get("RABBITMQ_PASSWORD", "")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"stdout": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["stdout"], "level": "INFO"},
    "loggers": {
        "djangosaml2": {"level": "INFO"},
        "pika": {"level": "WARNING"},
    },
}

# djangosaml2
SAML_SESSION_COOKIE_NAME = "saml_session"
SAML_SESSION_COOKIE_SAMESITE = "None"
SAML_DJANGO_USER_MAIN_ATTRIBUTE = "sso_subject"
SAML_CREATE_UNKNOWN_USER = True
SAML_DEFAULT_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
# Prefer POST if the configured IdP supports SAML logout.
SAML_LOGOUT_REQUEST_PREFERRED_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
SAML_CSP_HANDLER = ""
SAML_IGNORE_LOGOUT_ERRORS = True
ACS_DEFAULT_REDIRECT_URL = "/"
SAML_ATTRIBUTE_MAPPING = dict(SAML_ATTRIBUTE_MAPPING)

# A database cache is shared by every gunicorn worker; it backs SAML replay
# protection. Created by ``manage.py createcachetable`` at container start.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}

# The research organisation directory (it42.common.research_orgs), mounted read-only into
# every zone.
RESEARCH_ORGS_FILE = Path(
    env("RESEARCH_ORGS_FILE", str(BASE_DIR / "config" / "research_orgs.toml"))
)

# Applications carry their PDFs base64-encoded inside the event. RabbitMQ 4 rejects
# messages over 16 MiB by default, so cap what one application can attach.
MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
