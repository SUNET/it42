import os

ROLES = ("core", "org", "ro")


def settings_module() -> str:
    """Pick the settings module from APP_ROLE (core, org or ro)."""
    role = os.environ.get("APP_ROLE", "core")
    if role not in ROLES:
        raise RuntimeError(f"APP_ROLE must be one of {', '.join(ROLES)}, not {role!r}")
    return f"it42.settings.{role}"
