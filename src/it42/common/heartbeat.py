from pathlib import Path


def beat(name: str) -> None:
    """Touch /tmp/<name>.alive; the worker health check looks at its age."""
    Path(f"/tmp/{name}.alive").touch()  # noqa: S108 (container-local marker)
