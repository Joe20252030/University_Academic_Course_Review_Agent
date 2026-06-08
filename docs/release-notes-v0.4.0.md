# UACRAgent v0.4.0 — Release Notes

**Released:** 2026-06-07  
**Full changelog:** [CHANGELOG.md](../CHANGELOG.md)  
**Downloads:** [GitHub Releases](https://github.com/Joe20252030/University_Academic_Course_Review_Agent/releases/tag/v0.4.0)

---

## What's new

### Auto-updater

The app now checks for new GitHub releases silently 4 seconds after launch. When a newer version is found, a non-blocking dialog presents three choices:

- **Update Now** — downloads the platform-specific installer with a live progress percentage, then:
  - **macOS**: opens the `.dmg` in Finder so you can drag `UACRAgent.app` to `/Applications`. The current session stays open.
  - **Windows**: launches the `.exe` installer as a detached background process and exits the running app so the installer can replace files in place.
- **Remind Me Later** — dismisses the dialog; the check runs again on the next launch.
- **Skip This Version** — persists the skipped release tag to `~/.uacragent/config.json` so that version never prompts again (unless explicitly cleared).

Any network or API error during the check is handled silently — the updater never blocks launch or crashes the app.

The check uses the `/releases` list endpoint so **pre-releases are included**. The highest-versioned release that carries a platform-specific installer asset is offered. Draft releases are always excluded.

### PPTX embedded-image vision extraction

When you attach a `.pptx` file in the desktop chat, embedded image shapes (photos, diagrams, charts) are now extracted and sent to the LLM as base64-encoded vision inputs. The model can now *see* slide images rather than receiving silence where images were.

Limits: up to 5 images per file; images over 5 MB are skipped individually. Active only for vision-capable providers (Gemini, OpenAI). Text-only providers (DeepSeek) receive text content only, along with a visible warning.

### Extraction-failure warnings in chat

Attachment extraction failures — `python-pptx` not installed, legacy `.ppt` format, corrupt files, unsupported MIME types — now surface as visible ⚠️ system messages in the chat area. Previously these conditions were forwarded to the LLM silently with no indication anything went wrong.

### Image-count notes in indexed PPTX slides

When indexing `.pptx` files into the local Chroma store without Tesseract OCR installed, slides containing embedded pictures now include a note such as `[2 images on this slide — text inside images not extracted]`. The LLM can then at least acknowledge the presence of visual content when answering questions.

### App Settings save-reminder banner

The App Settings dialog now shows a fixed notice at the top — *"Appearance changes preview instantly. Click Save to confirm all changes, or Cancel to revert."* — matching the existing Session Settings banner style. Available in English and Simplified Chinese.

---

## Bug fixes

### Updater dialog-close races (two independent guards)

If the update dialog was dismissed via the `×` title-bar button while a download was still in progress, `_on_download_done` scheduled `_apply_now` unconditionally on completion. On macOS this opened the `.dmg` unexpectedly with no dialog context; on Windows the app called `sys.exit(0)` silently. A second, narrower window existed even after the first fix: if the dialog was closed *after* `_on_download_done` passed its check but *before* the 500 ms (macOS) / 1000 ms (Windows) settle delay elapsed, `_apply_now` still ran.

Fixed with two independent `winfo_exists()` guards — one in `_on_download_done` (before scheduling `_apply_now`) and one at the top of `_apply_now` itself (before calling `apply_update()`). Both paths delete the downloaded file and clear `_pending_update_path` when the dialog is gone.

### `_on_download_failed` TclError to stderr

The widget calls in the download-failure handler (`_status_var.set` and `_later_btn.set_state`) were unguarded. If the handler fired after the dialog was already destroyed, both raised `TclError`, which Tkinter's `report_callback_exception` printed to stderr. Both calls are now individually wrapped in `try/except Exception: pass`.

### API workspace cleanup missing symlink guards

`_cleanup_expired_api_workspaces` had no symlink check before calling `shutil.rmtree`. A symlink placed — or swapped in — at a workspace path could have directed `rmtree` to an arbitrary location. Fixed with two independent checks: an initial `ws.is_symlink()` guard when the directory is first considered, and a TOCTOU re-check immediately before `rmtree`. Mirrors the defence-in-depth already present in `delete_session()`.

### `_running_version()` reading stale pip metadata

The updater called `importlib.metadata.version("uacragent")` directly, which reads the `.dist-info` from the *last* `pip install`. If `pyproject.toml` was bumped without re-running `pip install -e .`, the updater compared against the wrong baseline. Fixed: `_running_version()` now delegates to `uacragent.__version__`, which has the correct `importlib.metadata` + `pyproject.toml` fallback chain.

### `save_session()` orphaned directory

A failed ownership-marker write during `save_session()` rolled back `session.json` but left an empty `.uacragent/` directory behind. The pre-check at the top of `save_session()` then permanently refused all future saves for that session (empty dir with no `owner.json` is treated as a foreign folder). Fixed: a `_agent_dir_was_new` flag tracks whether this call created the directory; both failure paths now remove it via `os.rmdir()`.

### PPTX embedded images bypassed provider vision guard

Embedded image blobs extracted from `.pptx` attachments were appended as `image_url` parts inside `_build_human_message()`, completely bypassing the non-vision provider guard in `ConversationAgent.chat()`. Text-only providers received multimodal content they cannot handle. Fixed: `_provider_supports_vision()` is checked before adding PPTX image parts; non-vision providers receive a `ui_warning` instead.

### Auto-updater skipped all pre-releases

The `/releases/latest` endpoint is documented by GitHub to exclude pre-releases and returns HTTP 404 when every release in the repository is a pre-release. The updater now calls `/releases?per_page=20`, which returns all releases including pre-releases. Draft releases are still excluded. Among all valid candidates, the one with the highest version number that carries a platform-specific installer asset is selected.

### `CERTIFICATE_VERIFY_FAILED` in frozen macOS builds

PyInstaller-frozen apps on macOS cannot reach the system certificate store through the standard `ssl` module, causing every HTTPS request from `urllib` to raise `ssl.SSLCertVerificationError`. Fixed by introducing `_make_ssl_context()`, which builds an `ssl.SSLContext` backed by `certifi`'s bundled CA bundle (`certifi.where()`). The context is passed to every `urlopen` call in the updater. Falls back to the default context when `certifi` is unavailable. `certifi` is added to `requirements.txt` and bundled via `collect_data_files("certifi")` in both PyInstaller specs.

### `check_for_update()` unexpected-response guard updated

Now that the endpoint returns a JSON list, the type guard after JSON parsing checks `isinstance(data, list)` instead of `isinstance(data, dict)`. Non-list payloads (proxy error pages, etc.) return `None` with a warning log.

### Output panel `stat()` TOCTOU

`fpath.stat().st_size` in the Generated Outputs panel could raise `FileNotFoundError` if a file was deleted externally while the dialog was open. Now wrapped in `try/except OSError`; falls back to `"—"` for the size label.

### `__init__.py` hardcoded version fallback

The bare-source fallback `__version__ = "0.3.2"` required manual editing on every release. Fixed: the fallback now reads `pyproject.toml` dynamically via regex so only `pyproject.toml` needs updating per release.

---

## Internal changes

- **`check_for_update()` endpoint** — switched from `/releases/latest` to `/releases?per_page=20`. The new implementation iterates all returned releases and picks the highest-versioned candidate with a matching asset.
- **`certifi` added as runtime dependency** — listed in `requirements.txt`; collected into both `UACRAgent_mac.spec` and `UACRAgent_win.spec`. Windows frozen apps use SChannel and don't require it, but it is bundled for consistency.
- **`_make_ssl_context()` helper** — new internal function in `updater.py` that returns a `certifi`-backed SSL context. Used by both `urlopen` calls (API check and asset download).
- **`workspace_manager.py` import ordering** — the `_safe_rmtree` import is now positioned above `logger = logging.getLogger(__name__)`, following standard module-level import ordering with no `# noqa` override.
- **`_safe_rmtree` consolidated** — `workspace_manager.py` and `vectorstore.py` previously both carried identical copies. The canonical implementation now lives in `workspace.py`; both callers import from there.
- **`_extract_file_text()` return type** — changed from `str` to `tuple[str, str | None]`. The second element is a user-facing warning string on extraction failure, or `None` on success.

---

## Test coverage

**515 tests, all passing** — up from 426 in v0.3.1.

89 new updater-specific tests span 11 sections: `_parse_version`, all `check_for_update` branches (newer / same / older / skipped / no asset / network error / non-list JSON / pre-release included / draft excluded / multi-release best-candidate / skipped-version fall-through), `download_update` (success, progress, no `Content-Length`, failure cleanup), `apply_update` (macOS stays running, Windows exits, unsupported platform raises), skip-version persistence round-trip, macOS/Windows window-behaviour invariants, `_pending_update_path` cleanup on close, two-layer dialog-closed guard (Guard 1 before download done; Guard 2 during settle delay), and `_on_download_failed` widget-call robustness.
