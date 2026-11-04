import os
from pathlib import Path

import pytest
from django.core.cache import cache

from it42.common import research_orgs

os.environ.pop("POSTGRES_HOST", None)

# The tracked example directory: Uppsala University (uu), KTH (kth) and RISE (rise).
RESEARCH_ORGS_EXAMPLE = (
    Path(__file__).resolve().parents[1] / "config" / "research_orgs.toml.example"
)


@pytest.fixture(autouse=True)
def _test_settings(settings, tmp_path: Path) -> None:
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.RESEARCH_ORGS_FILE = RESEARCH_ORGS_EXAMPLE
    research_orgs.directory.cache_clear()
    # LocMemCache instances share module-level storage; start every test empty.
    cache.clear()
