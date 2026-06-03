# -*- coding: utf-8 -*-
"""Auto-updater: check GitHub releases and download / apply installer packages.

Architecture
------------
UpdateChecker.check()        -- called in a background thread
  -> GitHub Releases API (stdlib urllib, zero extra dependencies)
  -> compares tag version against the running package version
  -> returns UpdateInfo | None

UpdateDownloader.download()  -- called in a background thread
  -> streams the asset to a temp file
  -> reports progress via a callback (bytes_received, total_bytes)
  -> returns Path to downloaded file

apply_update(path)           -- called on the main thread
  macOS : opens the .dmg in Finder so the user can drag-install
  Windows : launches the .exe installer then quits the app

Skipping a version
------------------
The user can choose "Skip this version" in the update dialog.
The skipped version tag is persisted in ~/.uacragent/config.json
so the same release never prompts again.

Asset name convention (must match GitHub release uploads):
  macOS   : UACRAgent-v{version}-macOS-AppleSilicon.dmg
  Windows : UACRAgent-v{version}-windows-x64-setup.exe
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
import urllib.request
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GITHUB_REPO   = "Joe20252030/University_Academic_Course_Review_Agent"
_API_URL       = f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest"
_API_TIMEOUT   = 10   # seconds for the GitHub API call
_DL_CHUNK_SIZE = 64 * 1024  # 64 KB read chunks during download

# Platform-specific asset name patterns.
# {version} is substituted with the tag version string (without leading "v").
_ASSET_PATTERN: dict[str, str] = {
    "darwin": "UACRAgent-v{version}-macOS-AppleSilicon.dmg",
    "win32":  "UACRAgent-v{version}-windows-x64-setup.exe",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UpdateInfo:
    """Describes an available update retrieved from GitHub Releases."""

    tag: str                    # e.g. "v0.4.0"
    version: str                # e.g. "0.4.0"  (tag without leading "v")
    download_url: str           # direct browser_download_url of the asset
    asset_name: str             # filename of the asset
    body: str = ""              # release notes (markdown)
    html_url: str = ""          # GitHub release page URL


# ---------------------------------------------------------------------------
# Version comparison helpers
# ---------------------------------------------------------------------------

def _parse_version(ver: str) -> tuple[int, ...]:
    """Parse a semver string "MAJOR.MINOR.PATCH" into a comparable tuple.

    Leading "v" is stripped so both "0.4.0" and "v0.4.0" work.
    Non-numeric components are treated as 0 so pre-release tags degrade
    gracefully instead of raising.
    """
    ver = ver.lstrip("v").strip()
    parts: list[int] = []
    for segment in ver.split(".")[:3]:
        try:
            parts.append(int(segment))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def _running_version() -> str:
    """Return the currently-installed package version string."""
    try:
        from importlib.metadata import version as _iv
        return _iv("uacragent")
    except Exception:
        # Fallback when the package is run from source without being installed.
        try:
            import uacragent as _pkg
            return getattr(_pkg, "__version__", "0.0.0")
        except Exception:
            return "0.0.0"


# ---------------------------------------------------------------------------
# Skipped-version persistence
# ---------------------------------------------------------------------------
# These are thin re-exports of the canonical implementations in persistence.py.
# Both modules are in the same package (infra/) with no circular dependency,
# so a direct import is safe.  app.py imports these from updater.py for
# locality; persistence.py is the single source of truth for config I/O.

from uacragent.infra.persistence import (  # noqa: E402
    get_skipped_update_version,
    set_skipped_update_version,
)


def clear_skipped_update_version() -> None:
    """Remove the skipped-version record (e.g. when forcing a re-check)."""
    set_skipped_update_version("")


# ---------------------------------------------------------------------------
# Release check
# ---------------------------------------------------------------------------

def check_for_update() -> UpdateInfo | None:
    """Query the GitHub Releases API and return an UpdateInfo if a newer
    release is available for this platform, or None otherwise.

    This function is safe to call from a background thread.  It never raises
    -- all errors are logged at WARNING level and return None so the caller
    can treat any failure as "no update available."

    Reasons a None is returned:
    - No internet / DNS / TLS error
    - GitHub rate-limited (403/429)
    - Running on an unsupported platform (Linux)
    - Latest release has no matching asset for this platform
    - Current version >= latest release version
    - User previously chose to skip the latest version
    """
    platform = sys.platform
    if platform not in _ASSET_PATTERN:
        logger.debug("Auto-update not supported on platform '%s'.", platform)
        return None

    # ------------------------------------------------------------------
    # 1. Fetch latest release metadata
    # ------------------------------------------------------------------
    try:
        req = urllib.request.Request(
            _API_URL,
            headers={
                "Accept":     "application/vnd.github+json",
                "User-Agent": f"UACRAgent/{_running_version()}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(req, timeout=_API_TIMEOUT) as resp:
            import json as _json
            data: dict = _json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        logger.warning("Update check network error: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Update check failed: %s", exc)
        return None

    # ------------------------------------------------------------------
    # 2. Extract and compare versions
    # ------------------------------------------------------------------
    tag = data.get("tag_name", "").strip()
    if not tag:
        return None

    remote_version = tag.lstrip("v")
    current_version = _running_version()

    # Tuple comparison is element-wise (major, minor, patch), so this
    # triggers for ANY version strictly greater than the current one --
    # e.g. 0.3.2 → 0.3.3, 0.4.0, 1.0.0 all pass equally.
    if _parse_version(remote_version) <= _parse_version(current_version):
        logger.debug(
            "No update: current=%s, latest=%s", current_version, remote_version
        )
        return None

    # ------------------------------------------------------------------
    # 3. Check skip list
    # ------------------------------------------------------------------
    if get_skipped_update_version() == tag:
        logger.debug("Update %s was previously skipped by user.", tag)
        return None

    # ------------------------------------------------------------------
    # 4. Find the platform-specific asset
    # ------------------------------------------------------------------
    asset_name = _ASSET_PATTERN[platform].format(version=remote_version)
    download_url = ""
    for asset in data.get("assets", []):
        if asset.get("name") == asset_name:
            download_url = asset.get("browser_download_url", "")
            break

    if not download_url:
        logger.warning(
            "Update %s found but no asset named '%s' in the release.",
            tag, asset_name,
        )
        return None

    return UpdateInfo(
        tag=tag,
        version=remote_version,
        download_url=download_url,
        asset_name=asset_name,
        body=data.get("body", ""),
        html_url=data.get("html_url", ""),
    )


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_update(
    info: UpdateInfo,
    progress_cb: Callable[[int, int], None] | None = None,
) -> Path:
    """Download the release asset to a temporary file and return its path.

    Parameters
    ----------
    info:
        UpdateInfo returned by :func:`check_for_update`.
    progress_cb:
        Optional callable receiving ``(bytes_received, total_bytes)``.
        ``total_bytes`` is 0 when the server does not send Content-Length.

    Returns
    -------
    Path
        Path to the downloaded temporary file.  The caller is responsible
        for deleting it after installation (or on failure).

    Raises
    ------
    RuntimeError
        If the download fails for any reason.
    """
    suffix = Path(info.asset_name).suffix  # ".dmg" or ".exe"
    # Use the OS temp dir; delete=False so the file survives after close.
    fd, tmp_path_str = tempfile.mkstemp(prefix="uacragent_update_", suffix=suffix)
    os.close(fd)
    tmp_path = Path(tmp_path_str)

    try:
        req = urllib.request.Request(
            info.download_url,
            headers={"User-Agent": f"UACRAgent/{_running_version()}"},
        )
        with urllib.request.urlopen(req) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            received = 0
            with open(tmp_path, "wb") as out_fh:
                while True:
                    chunk = resp.read(_DL_CHUNK_SIZE)
                    if not chunk:
                        break
                    out_fh.write(chunk)
                    received += len(chunk)
                    if progress_cb:
                        try:
                            progress_cb(received, total)
                        except Exception:  # noqa: BLE001
                            pass
    except Exception as exc:  # noqa: BLE001
        # Clean up the partial download before propagating the error.
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"Download failed: {exc}") from exc

    return tmp_path


# ---------------------------------------------------------------------------
# Apply update
# ---------------------------------------------------------------------------

def apply_update(downloaded_path: Path) -> None:
    """Launch / open the downloaded installer.

    macOS
        Opens the .dmg in Finder.  The user drags the .app to /Applications
        themselves (the standard Mac install flow).  The app is NOT quit here
        because the user may want to finish their current session first.

    Windows
        Launches the .exe installer as a detached subprocess, then quits the
        running app so Windows can replace the executable files.  The installer
        handles uninstall + reinstall transparently (InnoSetup behaviour).

    Parameters
    ----------
    downloaded_path:
        Path returned by :func:`download_update`.
    """
    if sys.platform == "darwin":
        import subprocess
        subprocess.Popen(["open", str(downloaded_path)])

    elif sys.platform.startswith("win"):
        import subprocess
        # Launch installer detached so it survives the app quitting.
        subprocess.Popen(
            [str(downloaded_path), "/SILENT"],
            creationflags=subprocess.DETACHED_PROCESS
                          | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
        # Give the OS a moment to start the installer before we exit.
        time.sleep(0.5)
        sys.exit(0)

    else:
        raise RuntimeError(
            f"apply_update() is not implemented for platform '{sys.platform}'."
        )
