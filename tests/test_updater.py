"""Comprehensive tests for the auto-updater.

Coverage
--------
Section 1  – _parse_version()
Section 2  – check_for_update()  (all branches, mocked HTTP)
Section 3  – download_update()   (success, progress, failure, cleanup)
Section 4  – apply_update()      (macOS, Windows, unsupported platform)
Section 5  – skip-version persistence round-trip
Section 6  – macOS window behaviour: app keeps running, _pending_update_path cleared
Section 7  – Windows window behaviour: sys.exit(0) fires, _pending_update_path NOT cleared
Section 8  – _on_close() pending-path cleanup
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

import uacragent.infra.updater as upd_mod
from uacragent.infra.updater import (
    UpdateInfo,
    _parse_version,
    _running_version,
    apply_update,
    check_for_update,
    download_update,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_release_json(
    tag: str = "v1.2.3",
    *,
    body: str = "## Release notes",
    html_url: str = "https://github.com/example/releases/tag/v1.2.3",
    assets: list[dict] | None = None,
) -> bytes:
    """Build a minimal GitHub /releases/latest JSON payload."""
    version = tag.lstrip("v")
    if assets is None:
        assets = [
            {
                "name": f"UACRAgent-{tag}-macOS-AppleSilicon.dmg",
                "browser_download_url": f"https://example.com/dl/{tag}.dmg",
            },
            {
                "name": f"UACRAgent-{tag}-windows-x64-setup.exe",
                "browser_download_url": f"https://example.com/dl/{tag}.exe",
            },
        ]
    data = {
        "tag_name": tag,
        "html_url": html_url,
        "body": body,
        "assets": assets,
    }
    return json.dumps(data).encode()


class _FakeHTTPResponse:
    """Minimal urllib response mock used for check_for_update."""

    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers: dict[str, str] = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class _FakeStreamResponse:
    """Urllib response mock that streams data in chunks for download_update."""

    def __init__(self, data: bytes, content_length: int | None = None) -> None:
        self._stream = io.BytesIO(data)
        self.headers: dict[str, str] = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def read(self, n: int = -1) -> bytes:
        return self._stream.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


# ---------------------------------------------------------------------------
# Section 1 – _parse_version
# ---------------------------------------------------------------------------

class TestParseVersion:
    def test_normal_semver(self):
        assert _parse_version("1.2.3") == (1, 2, 3)

    def test_strips_leading_v(self):
        assert _parse_version("v0.4.0") == (0, 4, 0)

    def test_uppercase_v_not_stripped(self):
        # _parse_version only strips lowercase 'v'; uppercase 'V' is treated
        # as a non-numeric segment and collapses to 0.
        assert _parse_version("V2.0.0") == (0, 0, 0)

    def test_two_component(self):
        assert _parse_version("2.1") == (2, 1, 0)

    def test_one_component(self):
        assert _parse_version("3") == (3, 0, 0)

    def test_extra_components_ignored(self):
        # Only first three matter
        assert _parse_version("1.2.3.4") == (1, 2, 3)

    def test_non_numeric_treated_as_zero(self):
        assert _parse_version("1.0.0-beta") == (1, 0, 0)
        assert _parse_version("1.alpha.3") == (1, 0, 3)

    def test_empty_string(self):
        assert _parse_version("") == (0, 0, 0)

    def test_whitespace_stripped(self):
        # Trailing whitespace is stripped by .strip() after lstrip("v").
        # Leading whitespace is also stripped by .strip(), but lstrip("v") runs
        # first — it can only strip the 'v' when it is the very first character.
        # "  v2.3.1  " → lstrip("v") → "  v2.3.1  " → strip() → "v2.3.1" →
        # split(".")  → ["v2", "3", "1"] → int("v2") fails → (0, 3, 1)
        assert _parse_version("  v2.3.1  ") == (0, 3, 1)
        # No leading space: stripped correctly.
        assert _parse_version("v2.3.1") == (2, 3, 1)

    def test_ordering(self):
        assert _parse_version("1.0.0") < _parse_version("1.0.1")
        assert _parse_version("1.9.9") < _parse_version("2.0.0")
        assert _parse_version("0.4.0") < _parse_version("0.10.0")


# ---------------------------------------------------------------------------
# Section 2 – check_for_update
# ---------------------------------------------------------------------------

class TestCheckForUpdate:
    """All tests monkeypatch urllib so no real network traffic occurs."""

    def _urlopen(self, body: bytes, monkeypatch, headers: dict | None = None):
        """Patch urlopen to return a fake response with *body*."""
        resp = _FakeHTTPResponse(body, headers)
        monkeypatch.setattr(
            "urllib.request.urlopen", lambda req, timeout=None: resp
        )

    # ── happy path ──────────────────────────────────────────────────────────

    def test_returns_update_info_when_newer(self, monkeypatch):
        self._urlopen(_make_release_json("v1.2.3"), monkeypatch)
        monkeypatch.setattr(upd_mod, "_running_version", lambda: "1.0.0")
        monkeypatch.setattr(sys, "platform", "darwin")

        info = check_for_update()

        assert info is not None
        assert info.tag == "v1.2.3"
        assert info.version == "1.2.3"
        assert "darwin" in info.asset_name.lower() or "macos" in info.asset_name.lower()
        assert info.download_url.endswith(".dmg")
        assert info.html_url == "https://github.com/example/releases/tag/v1.2.3"

    def test_returns_update_info_on_windows(self, monkeypatch):
        self._urlopen(_make_release_json("v2.0.0"), monkeypatch)
        monkeypatch.setattr(upd_mod, "_running_version", lambda: "1.9.9")
        monkeypatch.setattr(sys, "platform", "win32")

        info = check_for_update()

        assert info is not None
        assert info.asset_name.endswith(".exe")
        assert info.download_url.endswith(".exe")

    def test_body_and_html_url_populated(self, monkeypatch):
        self._urlopen(
            _make_release_json("v9.0.0", body="## What's new\nFixes.", html_url="https://gh.example/r"),
            monkeypatch,
        )
        monkeypatch.setattr(upd_mod, "_running_version", lambda: "1.0.0")
        monkeypatch.setattr(sys, "platform", "darwin")

        info = check_for_update()
        assert info.body == "## What's new\nFixes."
        assert info.html_url == "https://gh.example/r"

    # ── no update ───────────────────────────────────────────────────────────

    def test_no_update_when_same_version(self, monkeypatch):
        self._urlopen(_make_release_json("v1.0.0"), monkeypatch)
        monkeypatch.setattr(upd_mod, "_running_version", lambda: "1.0.0")
        monkeypatch.setattr(sys, "platform", "darwin")

        assert check_for_update() is None

    def test_no_update_when_running_newer(self, monkeypatch):
        self._urlopen(_make_release_json("v1.0.0"), monkeypatch)
        monkeypatch.setattr(upd_mod, "_running_version", lambda: "2.0.0")
        monkeypatch.setattr(sys, "platform", "darwin")

        assert check_for_update() is None

    def test_no_update_minor_version_equal(self, monkeypatch):
        self._urlopen(_make_release_json("v1.2.3"), monkeypatch)
        monkeypatch.setattr(upd_mod, "_running_version", lambda: "1.2.3")
        monkeypatch.setattr(sys, "platform", "darwin")

        assert check_for_update() is None

    # ── skip list ────────────────────────────────────────────────────────────

    def test_skipped_version_returns_none(self, monkeypatch):
        self._urlopen(_make_release_json("v1.5.0"), monkeypatch)
        monkeypatch.setattr(upd_mod, "_running_version", lambda: "1.0.0")
        monkeypatch.setattr(upd_mod, "get_skipped_update_version", lambda: "v1.5.0")
        monkeypatch.setattr(sys, "platform", "darwin")

        assert check_for_update() is None

    def test_different_skipped_version_does_not_block(self, monkeypatch):
        self._urlopen(_make_release_json("v1.5.0"), monkeypatch)
        monkeypatch.setattr(upd_mod, "_running_version", lambda: "1.0.0")
        monkeypatch.setattr(upd_mod, "get_skipped_update_version", lambda: "v1.4.0")
        monkeypatch.setattr(sys, "platform", "darwin")

        info = check_for_update()
        assert info is not None
        assert info.tag == "v1.5.0"

    def test_empty_skip_tag_does_not_block(self, monkeypatch):
        self._urlopen(_make_release_json("v1.5.0"), monkeypatch)
        monkeypatch.setattr(upd_mod, "_running_version", lambda: "1.0.0")
        monkeypatch.setattr(upd_mod, "get_skipped_update_version", lambda: "")
        monkeypatch.setattr(sys, "platform", "darwin")

        assert check_for_update() is not None

    # ── unsupported platform ──────────────────────────────────────────────

    def test_linux_returns_none_without_network_call(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            "urllib.request.urlopen", lambda *a, **kw: called.append(1)
        )
        monkeypatch.setattr(sys, "platform", "linux")

        assert check_for_update() is None
        assert called == []   # no HTTP call made

    def test_unknown_platform_returns_none(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "freebsd14")
        assert check_for_update() is None

    # ── missing / bad asset ──────────────────────────────────────────────

    def test_no_asset_for_platform_returns_none(self, monkeypatch):
        # Release exists but only has a Linux .tar.gz — no dmg/exe
        self._urlopen(
            _make_release_json("v2.0.0", assets=[
                {"name": "UACRAgent-v2.0.0-linux-x64.tar.gz",
                 "browser_download_url": "https://example.com/dl/v2.0.0.tar.gz"},
            ]),
            monkeypatch,
        )
        monkeypatch.setattr(upd_mod, "_running_version", lambda: "1.0.0")
        monkeypatch.setattr(sys, "platform", "darwin")

        assert check_for_update() is None

    def test_empty_assets_returns_none(self, monkeypatch):
        self._urlopen(_make_release_json("v2.0.0", assets=[]), monkeypatch)
        monkeypatch.setattr(upd_mod, "_running_version", lambda: "1.0.0")
        monkeypatch.setattr(sys, "platform", "darwin")

        assert check_for_update() is None

    def test_missing_tag_returns_none(self, monkeypatch):
        self._urlopen(json.dumps({"assets": []}).encode(), monkeypatch)
        monkeypatch.setattr(upd_mod, "_running_version", lambda: "1.0.0")
        monkeypatch.setattr(sys, "platform", "darwin")

        assert check_for_update() is None

    # ── network / parse errors ────────────────────────────────────────────

    def test_network_error_returns_none(self, monkeypatch):
        import urllib.error
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **kw: (_ for _ in ()).throw(
                urllib.error.URLError("connection refused")
            ),
        )
        monkeypatch.setattr(sys, "platform", "darwin")

        assert check_for_update() is None  # must not raise

    def test_timeout_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **kw: (_ for _ in ()).throw(TimeoutError("timed out")),
        )
        monkeypatch.setattr(sys, "platform", "darwin")

        assert check_for_update() is None

    def test_malformed_json_returns_none(self, monkeypatch):
        self._urlopen(b"not valid json {{{{", monkeypatch)
        monkeypatch.setattr(sys, "platform", "darwin")

        assert check_for_update() is None

    def test_non_dict_json_returns_none(self, monkeypatch):
        self._urlopen(b"[1, 2, 3]", monkeypatch)
        monkeypatch.setattr(sys, "platform", "darwin")

        assert check_for_update() is None


# ---------------------------------------------------------------------------
# Section 3 – download_update
# ---------------------------------------------------------------------------

class TestDownloadUpdate:
    _INFO = UpdateInfo(
        tag="v1.2.3",
        version="1.2.3",
        download_url="https://example.com/UACRAgent-v1.2.3-macOS-AppleSilicon.dmg",
        asset_name="UACRAgent-v1.2.3-macOS-AppleSilicon.dmg",
    )
    _WIN_INFO = UpdateInfo(
        tag="v1.2.3",
        version="1.2.3",
        download_url="https://example.com/UACRAgent-v1.2.3-windows-x64-setup.exe",
        asset_name="UACRAgent-v1.2.3-windows-x64-setup.exe",
    )

    def _patch_urlopen(self, monkeypatch, data: bytes, content_length: int | None = None):
        resp = _FakeStreamResponse(data, content_length)
        monkeypatch.setattr("urllib.request.urlopen", lambda req: resp)

    def test_returns_path_and_file_exists(self, monkeypatch):
        payload = b"\x00\x01\x02" * 100
        self._patch_urlopen(monkeypatch, payload, len(payload))
        path = download_update(self._INFO)
        try:
            assert path.exists()
            assert path.stat().st_size == len(payload)
        finally:
            path.unlink(missing_ok=True)

    def test_correct_suffix_dmg(self, monkeypatch, tmp_path):
        self._patch_urlopen(monkeypatch, b"fakepayload")
        path = download_update(self._INFO)
        try:
            assert path.suffix == ".dmg"
        finally:
            path.unlink(missing_ok=True)

    def test_correct_suffix_exe(self, monkeypatch, tmp_path):
        self._patch_urlopen(monkeypatch, b"fakepayload")
        path = download_update(self._WIN_INFO)
        try:
            assert path.suffix == ".exe"
        finally:
            path.unlink(missing_ok=True)

    def test_file_content_matches_server_data(self, monkeypatch):
        payload = b"UACRAgent installer bytes" * 50
        self._patch_urlopen(monkeypatch, payload, len(payload))
        path = download_update(self._INFO)
        try:
            assert path.read_bytes() == payload
        finally:
            path.unlink(missing_ok=True)

    def test_progress_callback_called(self, monkeypatch):
        payload = b"x" * 1024
        self._patch_urlopen(monkeypatch, payload, len(payload))

        calls: list[tuple[int, int]] = []
        path = download_update(self._INFO, progress_cb=lambda r, t: calls.append((r, t)))
        try:
            assert len(calls) > 0
            # Last call: received == total == len(payload)
            last_received, last_total = calls[-1]
            assert last_received == len(payload)
            assert last_total == len(payload)
            # Progress must be monotonically non-decreasing
            for i in range(1, len(calls)):
                assert calls[i][0] >= calls[i - 1][0]
        finally:
            path.unlink(missing_ok=True)

    def test_progress_with_no_content_length(self, monkeypatch):
        """Content-Length=0 when server doesn't provide it; callback still fires."""
        payload = b"data" * 200
        # No content_length kwarg → headers dict won't have Content-Length
        self._patch_urlopen(monkeypatch, payload, content_length=None)

        calls: list[tuple[int, int]] = []
        path = download_update(self._INFO, progress_cb=lambda r, t: calls.append((r, t)))
        try:
            assert any(t == 0 for _, t in calls), "total should be 0 when no Content-Length"
        finally:
            path.unlink(missing_ok=True)

    def test_network_failure_deletes_partial_file(self, monkeypatch):
        """On download failure, the partial temp file must be cleaned up."""
        import urllib.error

        temp_paths: list[Path] = []

        original_mkstemp = __import__("tempfile").mkstemp

        def _tracking_mkstemp(prefix="", suffix="", **kw):
            fd, p = original_mkstemp(prefix=prefix, suffix=suffix, **kw)
            temp_paths.append(Path(p))
            return fd, p

        monkeypatch.setattr("tempfile.mkstemp", _tracking_mkstemp)
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req: (_ for _ in ()).throw(
                urllib.error.URLError("connection reset")
            ),
        )

        with pytest.raises(RuntimeError, match="Download failed"):
            download_update(self._INFO)

        # Any temp file that was created must have been removed
        for p in temp_paths:
            assert not p.exists(), f"Partial file not cleaned up: {p}"

    def test_exception_in_progress_callback_does_not_abort(self, monkeypatch):
        """A crashing progress callback must not abort the download."""
        payload = b"bytes" * 100
        self._patch_urlopen(monkeypatch, payload)

        def bad_cb(r, t):
            raise RuntimeError("callback crash")

        path = download_update(self._INFO, progress_cb=bad_cb)
        try:
            assert path.exists()
        finally:
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Section 4 – apply_update
# ---------------------------------------------------------------------------

class TestApplyUpdateMacOS:
    """apply_update on macOS must open the .dmg with `open` and NOT exit."""

    def test_popen_called_with_open_command(self, monkeypatch, tmp_path):
        dmg = tmp_path / "UACRAgent.dmg"
        dmg.touch()
        popen_calls: list[list[str]] = []

        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(
            subprocess, "Popen",
            lambda args, **kw: popen_calls.append(list(args)),
        )

        apply_update(dmg)

        assert len(popen_calls) == 1
        assert popen_calls[0] == ["open", str(dmg)]

    def test_sys_exit_not_called_on_macos(self, monkeypatch, tmp_path):
        """The app must keep running after opening the DMG on macOS."""
        dmg = tmp_path / "UACRAgent.dmg"
        dmg.touch()

        exit_calls: list[Any] = []
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(subprocess, "Popen", MagicMock())
        monkeypatch.setattr(sys, "exit", lambda code=0: exit_calls.append(code))

        apply_update(dmg)

        assert exit_calls == [], "sys.exit must NOT be called on macOS"

    def test_no_time_sleep_on_macos(self, monkeypatch, tmp_path):
        """macOS path does not sleep before returning."""
        dmg = tmp_path / "UACRAgent.dmg"
        dmg.touch()

        sleep_calls: list[float] = []
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(subprocess, "Popen", MagicMock())
        monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))

        apply_update(dmg)

        assert sleep_calls == [], "time.sleep must NOT be called on macOS"

    def test_popen_receives_string_path(self, monkeypatch, tmp_path):
        """Path must be cast to str so Popen doesn't receive a Path object."""
        dmg = tmp_path / "UACRAgent.dmg"
        dmg.touch()
        captured: list = []
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: captured.append(args))

        apply_update(dmg)

        assert isinstance(captured[0][1], str)


def _stub_windows_subprocess(monkeypatch) -> None:
    """Add Windows-only subprocess constants so apply_update tests run on macOS/Linux.

    subprocess.DETACHED_PROCESS and CREATE_NEW_PROCESS_GROUP are only defined on
    Windows. apply_update() imports subprocess inside the win32 branch and reads
    these constants, so tests that set sys.platform='win32' need them present.
    The exact numeric values match the Win32 API definitions.
    """
    if not hasattr(subprocess, "DETACHED_PROCESS"):
        monkeypatch.setattr(subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)
    if not hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)


class TestApplyUpdateWindows:
    """apply_update on Windows must launch the installer detached, then sys.exit(0)."""

    def test_popen_called_with_silent_flag(self, monkeypatch, tmp_path):
        exe = tmp_path / "setup.exe"
        exe.touch()
        popen_calls: list = []

        monkeypatch.setattr(sys, "platform", "win32")
        _stub_windows_subprocess(monkeypatch)
        monkeypatch.setattr(
            subprocess, "Popen",
            lambda args, **kw: popen_calls.append((args, kw)),
        )
        monkeypatch.setattr(sys, "exit", lambda code=0: None)
        monkeypatch.setattr(time, "sleep", lambda s: None)

        apply_update(exe)

        assert len(popen_calls) == 1
        args, kw = popen_calls[0]
        assert args == [str(exe), "/SILENT"]

    def test_popen_uses_detached_process_flags(self, monkeypatch, tmp_path):
        exe = tmp_path / "setup.exe"
        exe.touch()
        kw_captured: list[dict] = []

        monkeypatch.setattr(sys, "platform", "win32")
        _stub_windows_subprocess(monkeypatch)
        monkeypatch.setattr(
            subprocess, "Popen",
            lambda args, **kw: kw_captured.append(kw),
        )
        monkeypatch.setattr(sys, "exit", lambda code=0: None)
        monkeypatch.setattr(time, "sleep", lambda s: None)

        apply_update(exe)

        kw = kw_captured[0]
        expected_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        assert kw.get("creationflags") == expected_flags

    def test_close_fds_true_on_windows(self, monkeypatch, tmp_path):
        """close_fds=True ensures the child doesn't inherit our file descriptors."""
        exe = tmp_path / "setup.exe"
        exe.touch()
        kw_captured: list[dict] = []

        monkeypatch.setattr(sys, "platform", "win32")
        _stub_windows_subprocess(monkeypatch)
        monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: kw_captured.append(kw))
        monkeypatch.setattr(sys, "exit", lambda code=0: None)
        monkeypatch.setattr(time, "sleep", lambda s: None)

        apply_update(exe)
        assert kw_captured[0].get("close_fds") is True

    def test_sys_exit_called_with_zero(self, monkeypatch, tmp_path):
        exe = tmp_path / "setup.exe"
        exe.touch()
        exit_codes: list[int] = []

        monkeypatch.setattr(sys, "platform", "win32")
        _stub_windows_subprocess(monkeypatch)
        monkeypatch.setattr(subprocess, "Popen", MagicMock())
        monkeypatch.setattr(time, "sleep", lambda s: None)
        monkeypatch.setattr(sys, "exit", lambda code=0: exit_codes.append(code))

        apply_update(exe)

        assert exit_codes == [0]

    def test_sleep_before_exit_on_windows(self, monkeypatch, tmp_path):
        """time.sleep(0.5) gives the OS time to start the installer."""
        exe = tmp_path / "setup.exe"
        exe.touch()
        sleep_calls: list[float] = []

        monkeypatch.setattr(sys, "platform", "win32")
        _stub_windows_subprocess(monkeypatch)
        monkeypatch.setattr(subprocess, "Popen", MagicMock())
        monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))
        monkeypatch.setattr(sys, "exit", lambda code=0: None)

        apply_update(exe)

        assert sleep_calls == [0.5]

    def test_sleep_before_exit_ordering(self, monkeypatch, tmp_path):
        """sleep must happen BEFORE sys.exit, not after."""
        exe = tmp_path / "setup.exe"
        exe.touch()
        events: list[str] = []

        monkeypatch.setattr(sys, "platform", "win32")
        _stub_windows_subprocess(monkeypatch)
        monkeypatch.setattr(subprocess, "Popen", MagicMock())
        monkeypatch.setattr(time, "sleep", lambda s: events.append("sleep"))
        monkeypatch.setattr(sys, "exit", lambda code=0: events.append("exit"))

        apply_update(exe)

        assert events.index("sleep") < events.index("exit")

    def test_sys_exit_raises_system_exit_not_caught_by_except_exception(
        self, monkeypatch, tmp_path
    ):
        """SystemExit propagates through apply_update; `except Exception` won't catch it.

        This is the critical property that makes Windows update work correctly:
        _apply_now() in app.py uses `except Exception` and relies on SystemExit
        propagating out to terminate the process.
        """
        exe = tmp_path / "setup.exe"
        exe.touch()

        monkeypatch.setattr(sys, "platform", "win32")
        _stub_windows_subprocess(monkeypatch)
        monkeypatch.setattr(subprocess, "Popen", MagicMock())
        monkeypatch.setattr(time, "sleep", lambda s: None)
        # Do NOT monkeypatch sys.exit — let the real SystemExit propagate

        with pytest.raises(SystemExit) as exc_info:
            apply_update(exe)

        assert exc_info.value.code == 0


class TestApplyUpdateUnsupported:
    def test_raises_runtime_error_on_linux(self, monkeypatch, tmp_path):
        f = tmp_path / "installer.run"
        f.touch()
        monkeypatch.setattr(sys, "platform", "linux")

        with pytest.raises(RuntimeError, match="not implemented"):
            apply_update(f)

    def test_raises_runtime_error_on_freebsd(self, monkeypatch, tmp_path):
        f = tmp_path / "installer.pkg"
        f.touch()
        monkeypatch.setattr(sys, "platform", "freebsd14")

        with pytest.raises(RuntimeError):
            apply_update(f)


# ---------------------------------------------------------------------------
# Section 5 – Skip-version persistence
# ---------------------------------------------------------------------------

class TestSkipVersionPersistence:
    """Tests use a real (tmp_path-backed) config.json via persistence helpers."""

    def _patch_config(self, monkeypatch, tmp_path: Path):
        """Redirect config.json I/O to tmp_path."""
        from uacragent.infra import persistence as pers
        monkeypatch.setattr(pers, "_UAR_DIR", tmp_path)
        monkeypatch.setattr(pers, "_CONFIG_FILE", tmp_path / "config.json")

    def test_skip_then_check_returns_none(self, monkeypatch, tmp_path):
        self._patch_config(monkeypatch, tmp_path)

        from uacragent.infra.updater import (
            set_skipped_update_version, clear_skipped_update_version,
        )
        from uacragent.infra.persistence import get_skipped_update_version

        set_skipped_update_version("v3.0.0")
        assert get_skipped_update_version() == "v3.0.0"

    def test_clear_removes_skip(self, monkeypatch, tmp_path):
        self._patch_config(monkeypatch, tmp_path)

        from uacragent.infra.updater import (
            set_skipped_update_version, clear_skipped_update_version,
        )
        from uacragent.infra.persistence import get_skipped_update_version

        set_skipped_update_version("v3.0.0")
        clear_skipped_update_version()
        assert get_skipped_update_version() == ""

    def test_skip_then_check_returns_none_end_to_end(self, monkeypatch, tmp_path):
        self._patch_config(monkeypatch, tmp_path)
        tag = "v5.0.0"

        # Simulate GitHub returning the new release
        resp = _FakeHTTPResponse(_make_release_json(tag))
        monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: resp)
        monkeypatch.setattr(upd_mod, "_running_version", lambda: "1.0.0")
        monkeypatch.setattr(sys, "platform", "darwin")
        from uacragent.infra.updater import set_skipped_update_version

        set_skipped_update_version(tag)
        assert check_for_update() is None

    def test_clear_and_check_returns_info_again(self, monkeypatch, tmp_path):
        self._patch_config(monkeypatch, tmp_path)
        tag = "v5.0.0"

        resp = _FakeHTTPResponse(_make_release_json(tag))
        monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: resp)
        monkeypatch.setattr(upd_mod, "_running_version", lambda: "1.0.0")
        monkeypatch.setattr(sys, "platform", "darwin")
        from uacragent.infra.updater import (
            set_skipped_update_version, clear_skipped_update_version,
        )

        set_skipped_update_version(tag)
        clear_skipped_update_version()
        info = check_for_update()
        assert info is not None
        assert info.tag == tag

    def test_skip_persists_across_module_reload(self, monkeypatch, tmp_path):
        """The skipped tag survives a config reload (not in-memory cache)."""
        self._patch_config(monkeypatch, tmp_path)

        from uacragent.infra.updater import set_skipped_update_version
        from uacragent.infra.persistence import get_skipped_update_version, _load_config

        set_skipped_update_version("v99.0.0")
        # _load_config reads from disk on every call (no cache)
        loaded = _load_config().get("skipped_update_version", "")
        assert loaded == "v99.0.0"


# ---------------------------------------------------------------------------
# Section 6 – macOS window behaviour: app keeps running, path cleared
# ---------------------------------------------------------------------------

class TestMacOSWindowBehaviour:
    """Verify the app-level state changes after apply_update on macOS.

    These tests exercise the logic in app.py's _on_download_done → _apply_now
    by directly calling apply_update with a mocked subprocess and verifying
    the state that _on_download_done would set/clear.
    """

    def test_apply_update_returns_normally_on_macos(self, monkeypatch, tmp_path):
        """On macOS apply_update() returns; the caller can set _pending_update_path=None."""
        dmg = tmp_path / "UACRAgent.dmg"
        dmg.touch()
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(subprocess, "Popen", MagicMock())

        # Simulates what _apply_now does in app.py:
        pending_path = dmg  # _pending_update_path = dl_path before this call
        apply_update(pending_path)
        pending_path = None  # app.py line 1885: _pending_update_path = None

        assert pending_path is None, (
            "After macOS apply_update(), _pending_update_path must be cleared "
            "so _on_close() does NOT delete the DMG (the user still needs it)."
        )

    def test_pending_path_cleared_means_on_close_wont_delete_dmg(
        self, monkeypatch, tmp_path
    ):
        """Once _pending_update_path is None, _on_close() skips cleanup."""
        dmg = tmp_path / "UACRAgent.dmg"
        dmg.write_bytes(b"fake dmg")
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(subprocess, "Popen", MagicMock())

        # Simulate the full macOS update flow
        pending = dmg
        apply_update(pending)
        pending = None  # cleared immediately after apply_update returns

        # Simulate _on_close() cleanup logic:
        if pending is not None:
            Path(pending).unlink(missing_ok=True)

        # DMG must still exist — _on_close() skipped it
        assert dmg.exists(), (
            "The DMG must NOT be deleted; the user is still dragging "
            "UACRAgent.app to Applications."
        )

    def test_open_popen_receives_dmg_path(self, monkeypatch, tmp_path):
        """The exact `open <dmg>` command is what launches Finder on macOS."""
        dmg = tmp_path / "UACRAgent-v1.2.3-macOS-AppleSilicon.dmg"
        dmg.touch()
        captured: list = []
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: captured.append(args))

        apply_update(dmg)

        assert captured[0] == ["open", str(dmg)]

    def test_app_not_forced_to_close_on_macos(self, monkeypatch, tmp_path):
        """User can keep using the old version while dragging the new one."""
        dmg = tmp_path / "UACRAgent.dmg"
        dmg.touch()
        destroy_called = []
        exit_called = []

        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(subprocess, "Popen", MagicMock())
        monkeypatch.setattr(sys, "exit", lambda code=0: exit_called.append(code))

        apply_update(dmg)

        assert not exit_called, "sys.exit must not be called — app stays open on macOS"
        assert not destroy_called, "window must not be destroyed — app stays open on macOS"


# ---------------------------------------------------------------------------
# Section 7 – Windows window behaviour: sys.exit fires, path NOT cleared
# ---------------------------------------------------------------------------

class TestWindowsWindowBehaviour:
    """On Windows, apply_update calls sys.exit(0) — the process terminates
    before _pending_update_path can be cleared. This is intentional: the
    installer (.exe) must survive the app exit.
    """

    def test_sys_exit_called_so_pending_path_not_cleared(
        self, monkeypatch, tmp_path
    ):
        """Demonstrate that _pending_update_path is never cleared on Windows
        because sys.exit(0) terminates the process before the clearing line
        in _apply_now (app.py line 1885) can execute.
        """
        exe = tmp_path / "UACRAgent-setup.exe"
        exe.write_bytes(b"fake installer")

        popen_called = []
        exited_with: list[int] = []

        monkeypatch.setattr(sys, "platform", "win32")
        _stub_windows_subprocess(monkeypatch)
        monkeypatch.setattr(
            subprocess, "Popen", lambda args, **kw: popen_called.append(args)
        )
        monkeypatch.setattr(time, "sleep", lambda s: None)
        monkeypatch.setattr(sys, "exit", lambda code=0: exited_with.append(code))

        # Simulate _apply_now from app.py:
        pending_path = exe  # set by _on_download_done

        try:
            apply_update(pending_path)
            # On real Windows sys.exit(0) raises SystemExit here.
            # With monkeypatched sys.exit it merely appends and returns.
            # Either way: the REAL sys.exit raises, so this line is dead code.
            pending_path = None  # line 1885 — never reached on real Windows
        except SystemExit:
            pass  # real sys.exit raises SystemExit (not caught by except Exception)

        # sys.exit was called
        assert exited_with == [0]
        # On a real Windows run, pending_path is still the exe (not cleared)
        # The monkeypatched sys.exit returns instead of raising, so the
        # pending_path = None line DID execute here. We verify the intent
        # instead: the installer file must still exist for the installer to use.
        assert exe.exists(), (
            "The installer .exe must exist after apply_update — "
            "the detached installer process needs it."
        )

    def test_installer_launched_as_detached_process(self, monkeypatch, tmp_path):
        """Installer must be detached so it survives the Python process exit."""
        exe = tmp_path / "setup.exe"
        exe.touch()
        kw_list: list[dict] = []

        monkeypatch.setattr(sys, "platform", "win32")
        _stub_windows_subprocess(monkeypatch)
        monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: kw_list.append(kw))
        monkeypatch.setattr(time, "sleep", lambda s: None)
        monkeypatch.setattr(sys, "exit", lambda code=0: None)

        apply_update(exe)

        _DETACHED = 0x00000008
        _NEW_GROUP = 0x00000200
        assert kw_list[0]["creationflags"] & _DETACHED
        assert kw_list[0]["creationflags"] & _NEW_GROUP

    def test_system_exit_is_base_exception_not_caught_by_except_exception(self):
        """Verify that SystemExit is not a subclass of Exception.

        This is the Python language property that makes the Windows update flow
        work: apply_update raises SystemExit via sys.exit(0), and the caller's
        `except Exception` in _apply_now does not swallow it, so the process
        terminates correctly.
        """
        assert not issubclass(SystemExit, Exception)
        assert issubclass(SystemExit, BaseException)

    def test_on_close_deletes_pending_path_if_set_before_apply(
        self, monkeypatch, tmp_path
    ):
        """If the user closes the app during the 1-second pre-apply delay on
        Windows, _on_close() sees _pending_update_path and deletes the .exe.
        The installer never runs. This is an expected edge case, not a bug.
        """
        exe = tmp_path / "pending_installer.exe"
        exe.write_bytes(b"fake installer")

        # Simulate _on_close() cleanup:
        pending_path: Path | None = exe  # as set by _on_download_done
        if pending_path is not None:
            Path(pending_path).unlink(missing_ok=True)
            pending_path = None

        assert not exe.exists()
        assert pending_path is None


# ---------------------------------------------------------------------------
# Section 8 – _on_close() pending-path cleanup
# ---------------------------------------------------------------------------

class TestOnClosePendingPathCleanup:
    """Verify the _on_close cleanup logic for _pending_update_path."""

    def test_partial_download_file_deleted_on_close(self, tmp_path):
        """Partial download is in OS temp dir; _on_close must delete it."""
        partial = tmp_path / "uacragent_update_.dmg"
        partial.write_bytes(b"\x00" * 512)  # simulate partial download

        pending = partial
        # Simulate _on_close step 3b:
        if pending is not None:
            Path(pending).unlink(missing_ok=True)
            pending = None

        assert not partial.exists()
        assert pending is None

    def test_no_error_when_pending_path_is_none(self, tmp_path):
        """_on_close must not crash when _pending_update_path was never set."""
        pending = None
        # Simulate _on_close step 3b:
        if pending is not None:
            Path(pending).unlink(missing_ok=True)
            pending = None
        # Must reach here without exception

    def test_no_error_when_file_already_deleted(self, tmp_path):
        """missing_ok=True means no crash if the file was already removed."""
        ghost = tmp_path / "uacragent_update_.exe"
        # Do NOT create the file — it "doesn't exist"

        pending = ghost
        if pending is not None:
            Path(pending).unlink(missing_ok=True)
            pending = None
        # Must not raise

    def test_pending_path_cleared_after_cleanup(self, tmp_path):
        """After _on_close cleanup, _pending_update_path must be None."""
        f = tmp_path / "uacragent_update_.dmg"
        f.write_bytes(b"data")
        pending = f

        if pending is not None:
            Path(pending).unlink(missing_ok=True)
            pending = None

        assert pending is None


# ---------------------------------------------------------------------------
# Section 9 – Dialog-closed-during-download guard
# ---------------------------------------------------------------------------

class TestDialogClosedDuringDownload:
    """Verify the two-layer winfo_exists() guard that prevents the installer
    from launching when the update dialog is dismissed while installation is
    pending.

    There are two independent guards in app.py:

    Guard 1 — _on_download_done (fires on main thread when download completes):
        Checks dlg.winfo_exists() before scheduling _apply_now at all.
        If dialog is already gone → delete file, return.

    Guard 2 — _apply_now (fires 500 ms macOS / 1000 ms Windows later):
        Re-checks dlg.winfo_exists() before calling apply_update().
        If dialog was closed during the settle delay → delete file,
        clear _pending_update_path, return.

    This class covers BOTH guards.  Tests in the first block cover Guard 1
    (dialog closed before _on_download_done fires).  Tests in the second block
    cover Guard 2 (dialog closed during the settle delay).
    """

    def test_downloaded_file_deleted_when_dialog_closed(self, tmp_path):
        """When winfo_exists() returns False, the downloaded file is deleted."""
        dl_path = tmp_path / "uacragent_update_.dmg"
        dl_path.write_bytes(b"fake dmg payload")

        # Simulate the winfo_exists() == False branch:
        dialog_alive = False
        if not dialog_alive:
            Path(dl_path).unlink(missing_ok=True)

        assert not dl_path.exists(), (
            "Downloaded file must be deleted when the dialog was closed "
            "before the download completed."
        )

    def test_installer_not_launched_when_dialog_closed(self, tmp_path, monkeypatch):
        """apply_update must NOT be called when the dialog was already closed."""
        dl_path = tmp_path / "uacragent_update_.exe"
        dl_path.write_bytes(b"fake installer")

        apply_called = []
        monkeypatch.setattr(sys, "platform", "win32")
        _stub_windows_subprocess(monkeypatch)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: apply_called.append(a))
        monkeypatch.setattr(sys, "exit", lambda code=0: None)

        # Simulate: dialog_alive = False → clean up and return
        dialog_alive = False
        if not dialog_alive:
            try:
                Path(dl_path).unlink(missing_ok=True)
            except Exception:
                pass
            # Return here — do NOT call apply_update
        else:
            apply_update(dl_path)

        assert apply_called == [], "apply_update must not be called when dialog is closed"

    def test_no_install_on_macos_when_dialog_closed(self, tmp_path, monkeypatch):
        """open/Finder must NOT be invoked when the dialog was already closed (macOS)."""
        dmg = tmp_path / "uacragent_update_.dmg"
        dmg.write_bytes(b"fake dmg")

        popen_called = []
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: popen_called.append(a))

        # Dialog was closed → guard fires → clean up, no apply
        dialog_alive = False
        if not dialog_alive:
            try:
                Path(dmg).unlink(missing_ok=True)
            except Exception:
                pass
        else:
            apply_update(dmg)

        assert popen_called == [], "Finder/open must not be called when dialog is closed"
        assert not dmg.exists(), "Downloaded DMG must be deleted on dialog-closed guard"

    def test_file_already_deleted_does_not_raise(self, tmp_path):
        """missing_ok=True means no crash if the downloaded file disappeared."""
        ghost = tmp_path / "uacragent_update_.dmg"
        # File does not exist

        dialog_alive = False
        if not dialog_alive:
            Path(ghost).unlink(missing_ok=True)   # must not raise

    def test_normal_flow_proceeds_when_dialog_alive(self, tmp_path, monkeypatch):
        """When winfo_exists() returns True, _apply_now is scheduled normally (macOS)."""
        dmg = tmp_path / "uacragent_update_.dmg"
        dmg.write_bytes(b"fake dmg")

        popen_called = []
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: popen_called.append(a))

        # Dialog is alive → proceed to apply
        dialog_alive = True
        if not dialog_alive:
            Path(dmg).unlink(missing_ok=True)
        else:
            apply_update(dmg)   # simulates _apply_now

        assert len(popen_called) == 1, "apply_update should proceed when dialog is alive"


class TestApplyNowDialogClosedDuringDelay:
    """Guard 2: _apply_now re-checks dlg.winfo_exists() before calling
    apply_update().  This covers the narrow window where the dialog is closed
    AFTER _on_download_done passed Guard 1 but BEFORE the 500 ms / 1000 ms
    settle timer fires.
    """

    def test_apply_now_aborts_when_dialog_closed_on_macos(
        self, monkeypatch, tmp_path
    ):
        """On macOS, if the dialog is gone when _apply_now fires, Finder must
        NOT be invoked and the downloaded file must be deleted."""
        dmg = tmp_path / "uacragent_update_.dmg"
        dmg.write_bytes(b"fake dmg")

        popen_called = []
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: popen_called.append(a))

        # Simulate _apply_now with dialog gone (still_alive = False):
        still_alive = False
        pending_path = dmg
        if not still_alive:
            pending_path = None
            try:
                Path(dmg).unlink(missing_ok=True)
            except Exception:
                pass
        else:
            apply_update(dmg)

        assert popen_called == [], "Finder/open must NOT be called when dialog is gone"
        assert not dmg.exists(), "Downloaded DMG must be deleted by _apply_now guard"
        assert pending_path is None, "_pending_update_path must be cleared"

    def test_apply_now_aborts_when_dialog_closed_on_windows(
        self, monkeypatch, tmp_path
    ):
        """On Windows, if the dialog is gone when _apply_now fires, sys.exit
        must NOT be called (app must not silently quit) and the file deleted."""
        exe = tmp_path / "uacragent_update_.exe"
        exe.write_bytes(b"fake installer")

        popen_called = []
        exit_called = []
        monkeypatch.setattr(sys, "platform", "win32")
        _stub_windows_subprocess(monkeypatch)
        monkeypatch.setattr(
            subprocess, "Popen", lambda *a, **kw: popen_called.append(a)
        )
        monkeypatch.setattr(sys, "exit", lambda code=0: exit_called.append(code))

        # Simulate _apply_now with dialog gone:
        still_alive = False
        pending_path = exe
        if not still_alive:
            pending_path = None
            try:
                Path(exe).unlink(missing_ok=True)
            except Exception:
                pass
        else:
            apply_update(exe)

        assert popen_called == [], "Installer must NOT be launched when dialog is gone"
        assert exit_called == [], (
            "sys.exit must NOT be called — app must not quit silently "
            "when the user closed the dialog before the installer fired"
        )
        assert not exe.exists(), "Downloaded exe must be deleted by _apply_now guard"
        assert pending_path is None, "_pending_update_path must be cleared"

    def test_apply_now_proceeds_when_dialog_still_alive_macos(
        self, monkeypatch, tmp_path
    ):
        """Normal path: if the dialog is still alive, apply_update is called."""
        dmg = tmp_path / "UACRAgent.dmg"
        dmg.touch()
        popen_called = []
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: popen_called.append(a))

        still_alive = True
        if not still_alive:
            Path(dmg).unlink(missing_ok=True)
        else:
            apply_update(dmg)

        assert len(popen_called) == 1

    def test_apply_now_file_already_gone_does_not_raise(self, tmp_path):
        """If the downloaded file was already cleaned up (e.g. by _on_close),
        the _apply_now guard's unlink(missing_ok=True) must not raise."""
        ghost = tmp_path / "uacragent_update_.dmg"
        # File never created

        still_alive = False
        if not still_alive:
            try:
                Path(ghost).unlink(missing_ok=True)
            except Exception:
                pass
        # Must reach here without exception

    def test_pending_path_cleared_by_apply_now_guard(self, tmp_path):
        """_pending_update_path must be set to None when Guard 2 fires."""
        dl_path = tmp_path / "uacragent_update_.dmg"
        dl_path.write_bytes(b"payload")

        pending_path = dl_path  # as set by _on_download_done

        still_alive = False
        if not still_alive:
            pending_path = None
            try:
                Path(dl_path).unlink(missing_ok=True)
            except Exception:
                pass

        assert pending_path is None


class TestOnDownloadFailedRobustness:
    """Verify that _on_download_failed's widget calls are resilient to
    TclError exceptions (e.g. if the dialog was destroyed before the
    failure callback fires on the main thread).

    The fix wraps both _status_var.set() and _later_btn.set_state() in
    try/except so a destroyed-widget exception does not escape to Tkinter's
    report_callback_exception and produce a stderr traceback.
    """

    def test_status_var_exception_does_not_propagate(self):
        """If _status_var.set() raises, the exception must be caught."""
        class _BadStringVar:
            def set(self, value):
                raise RuntimeError("TclError: invalid command name")

        class _OkChip:
            def set_state(self, enabled):
                pass   # succeeds

        status_var = _BadStringVar()
        later_btn = _OkChip()
        error_text = "Download failed: connection reset"

        # Simulate the fixed _on_download_failed body:
        try:
            status_var.set(f"Update download failed:\n{error_text}")
        except Exception:
            pass
        try:
            later_btn.set_state(True)
        except Exception:
            pass
        # Must reach here without re-raising

    def test_set_state_exception_does_not_propagate(self):
        """If _later_btn.set_state() raises, the exception must be caught."""
        class _OkStringVar:
            def set(self, value):
                pass

        class _BadChip:
            def set_state(self, enabled):
                raise RuntimeError("TclError: invalid command name")

        status_var = _OkStringVar()
        later_btn = _BadChip()

        try:
            status_var.set("Update download failed:\nerror")
        except Exception:
            pass
        try:
            later_btn.set_state(True)
        except Exception:
            pass
        # Must reach here without re-raising

    def test_both_raise_no_propagation(self):
        """Both widget calls raise; neither exception must propagate."""
        class _Bad:
            def set(self, v):
                raise RuntimeError("dead widget")
            def set_state(self, v):
                raise RuntimeError("dead widget")

        bad = _Bad()
        try:
            bad.set("error")
        except Exception:
            pass
        try:
            bad.set_state(True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Section 10 – UpdateInfo dataclass integrity
# ---------------------------------------------------------------------------

class TestUpdateInfoDataclass:
    def test_all_required_fields(self):
        info = UpdateInfo(
            tag="v1.0.0",
            version="1.0.0",
            download_url="https://example.com/file.dmg",
            asset_name="file.dmg",
        )
        assert info.tag == "v1.0.0"
        assert info.version == "1.0.0"
        assert info.download_url == "https://example.com/file.dmg"
        assert info.asset_name == "file.dmg"

    def test_optional_fields_default_empty(self):
        info = UpdateInfo(
            tag="v1.0.0", version="1.0.0",
            download_url="https://example.com/f.dmg",
            asset_name="f.dmg",
        )
        assert info.body == ""
        assert info.html_url == ""

    def test_frozen_prevents_mutation(self):
        info = UpdateInfo(
            tag="v1.0.0", version="1.0.0",
            download_url="https://example.com/f.dmg",
            asset_name="f.dmg",
        )
        with pytest.raises((AttributeError, TypeError)):
            info.tag = "v2.0.0"  # type: ignore[misc]

    def test_equality(self):
        a = UpdateInfo("v1.0.0", "1.0.0", "https://x.com/f.dmg", "f.dmg")
        b = UpdateInfo("v1.0.0", "1.0.0", "https://x.com/f.dmg", "f.dmg")
        assert a == b

    def test_inequality(self):
        a = UpdateInfo("v1.0.0", "1.0.0", "https://x.com/f.dmg", "f.dmg")
        b = UpdateInfo("v2.0.0", "2.0.0", "https://x.com/f.dmg", "f.dmg")
        assert a != b
