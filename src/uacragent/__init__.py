from importlib.metadata import version as _version, PackageNotFoundError as _PackageNotFoundError

try:
    # Normal path: package is installed — metadata comes from the last
    # `pip install -e .` and is always authoritative for installed builds.
    __version__: str = _version("uacragent")
except _PackageNotFoundError:
    # Running directly from source without `pip install -e .`.
    # Parse the version from pyproject.toml so this fallback stays in sync
    # automatically — no second file to edit per release.
    try:
        from pathlib import Path as _Path
        import re as _re
        _toml = (_Path(__file__).parent.parent.parent / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        _m = _re.search(r'^version\s*=\s*"([^"]+)"', _toml, _re.MULTILINE)
        __version__ = _m.group(1) if _m else "0.0.0"
        del _Path, _re, _toml, _m
    except Exception:
        __version__ = "0.0.0"
