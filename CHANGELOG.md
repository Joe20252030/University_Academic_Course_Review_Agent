# Changelog

**Project website:** <https://joe20252030.github.io/University_Academic_Course_Review_Agent/>  
**Repository:** <https://github.com/Joe20252030/University_Academic_Course_Review_Agent>

All notable changes to UACRAgent are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.4.0] — 2026-06-07

### Added

- **Auto-updater** — the desktop app now checks for new releases silently in a
  background thread 4 seconds after launch. When a release newer than the
  running version is found on GitHub, a non-blocking dialog offers three
  choices:

  - **Update Now** — downloads the platform-specific installer asset with a
    live progress percentage, then:
    - macOS: opens the `.dmg` in Finder so the user can drag `UACRAgent.app`
      to `/Applications`. The current session stays open.
    - Windows: launches the `.exe` installer as a detached process
      (`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`) and exits the running
      app so the installer can replace files.
  - **Remind Me Later** — dismisses the dialog; the check runs again on the
    next launch.
  - **Skip This Version** — persists the skipped tag to
    `~/.uacragent/config.json`; that release never prompts again unless
    explicitly cleared.

  Asset name convention (must match GitHub release uploads):
  `UACRAgent-v{version}-macOS-AppleSilicon.dmg` /
  `UACRAgent-v{version}-windows-x64-setup.exe`.
  Any network or API error is handled silently — the update check never
  blocks launch or crashes the app.

- **PPTX embedded-image vision extraction (chat attach path)** — when a
  `.pptx` file is attached via the `+` button or paste, embedded image shapes
  (photos, diagrams, charts) are now extracted as base64-encoded vision parts
  and sent to the LLM alongside the extracted text. The LLM can now actually
  *see* slide images rather than receiving silence where images were. Limits:
  up to 5 images per file, images over 5 MB skipped individually. Vision parts
  are only added when the active provider supports vision inputs (non-vision
  providers such as DeepSeek receive text only, with a visible warning).

- **Image-count notes in indexed PPTX slides** — when indexing `.pptx` files
  into the session's Chroma store, slides that contain embedded pictures now
  include a note such as `[2 images on this slide — text inside images not
  extracted]` when OCR (Tesseract) is unavailable. The LLM can then answer
  questions about visual content at least by noting its presence.

- **App Settings save-reminder banner** — the App Settings dialog now shows a
  fixed notice at the top (matching the Session Settings banner style):
  *"Appearance changes preview instantly. Click Save to confirm all changes,
  or Cancel to revert."* Available in English and Simplified Chinese.

- **Comprehensive updater test suite** — 84 tests across 11 sections covering
  `_parse_version`, all `check_for_update` branches (newer/same/older/skipped/
  no asset/network error/non-dict JSON), `download_update` (success, progress,
  no Content-Length, failure cleanup), `apply_update` (macOS keeps running,
  Windows exits, unsupported platform raises), skip-version persistence
  round-trip, macOS/Windows window-behaviour invariants,
  `_pending_update_path` cleanup in `_on_close`, two-layer dialog-closed guard
  (Guard 1: before download done; Guard 2: during settle delay), and
  `_on_download_failed` widget-call robustness. Total: **510 tests, all
  passing**.

### Fixed

- **`check_for_update()` crash on non-dict GitHub API response** — if the
  GitHub Releases API returned a JSON array, `null`, or any non-dict value
  (e.g. a network proxy's error page), calling `.get()` on the result raised
  an uncaught `AttributeError`. Fixed with an `isinstance(data, dict)` guard
  immediately after JSON parsing; returns `None` on unexpected payloads.

- **Silent failure when `.pptx` chat attachment had extraction errors** —
  `_extract_file_text()` previously returned a bare string for all outcomes.
  Error notices (python-pptx not installed, legacy `.ppt` format, corrupt
  file, unsupported MIME type) were forwarded to the LLM silently, with no
  indication in the chat UI that anything went wrong. Fixed: the function now
  returns `(llm_text, ui_warning)`. A non-`None` `ui_warning` surfaces as a
  visible `⚠️` system message in the chat area for every extraction failure.

- **PPTX embedded images bypassed provider vision guard** — the vision guard
  in `ConversationAgent.chat()` filters out direct image attachments for
  non-vision providers, but PPTX image blobs were extracted and appended as
  `image_url` parts inside `_build_human_message()`, completely bypassing that
  guard. A DeepSeek (or any non-vision) provider received a multimodal content
  list it cannot handle. Fixed: `_provider_supports_vision()` is checked before
  adding PPTX image parts; non-vision providers receive a `ui_warning` instead.

- **Orphaned empty `.uacragent/` directory after `save_session()` failure** —
  `agent_dir.mkdir()` ran before the ownership-marker write. On any subsequent
  failure (marker write returns `False`, or `_atomic_write_text` raises),
  `session.json` was rolled back but `agent_dir` was left as an empty directory
  with no `owner.json`. The pre-check at the top of `save_session()` then
  permanently refused all future saves for that session (empty dir, no marker
  → treated as a foreign folder → returns `False`). Fixed: a
  `_agent_dir_was_new` flag tracks whether this call created the directory;
  both failure paths now call `_rollback_new_agent_dir()` which uses
  `os.rmdir()` (safe: only removes empty directories) to restore the filesystem
  to its prior state.

- **API workspace cleanup symlink guard (defence-in-depth)** —
  `_cleanup_expired_api_workspaces` in `api/main.py` now applies two
  independent symlink checks before touching any workspace directory:
  (1) an initial `ws.is_symlink()` check the moment a candidate directory is
  considered for cleanup, and (2) a TOCTOU re-check immediately before
  `shutil.rmtree(ws)` to close the window between the earlier check and the
  actual deletion. The original code had neither check, so a symlink placed —
  or swapped in — at the workspace path could have directed `rmtree` to an
  arbitrary location on disk. The two-check pattern mirrors the
  defence-in-depth already present in `delete_session()`.

- **Installer launched silently if update dialog closed during download** —
  if the user dismissed the update dialog via the `×` title-bar button while a
  download was still in progress, `_on_download_done` scheduled `_apply_now`
  unconditionally when the download completed. On macOS, Finder would open the
  `.dmg` unexpectedly with no dialog context. On Windows, the app would call
  `sys.exit(0)` silently — closing itself with no visible notification. A
  second, narrower window existed even after that guard was added: if the user
  closed the dialog *after* `_on_download_done` passed its check but *before*
  the 500 ms (macOS) / 1000 ms (Windows) settle delay expired, `_apply_now`
  still ran without re-checking the dialog state.
  Fixed with two independent guards:
  (1) `_on_download_done` checks `dlg.winfo_exists()` before scheduling
  `_apply_now` at all; and
  (2) `_apply_now` re-checks `dlg.winfo_exists()` at the start of its own
  body before calling `apply_update()`.
  In both cases the downloaded file is deleted and `_pending_update_path` is
  cleared when the dialog is gone.

- **`_on_download_failed` could produce a `TclError` traceback to stderr** —
  the widget calls in `_on_download_failed` (`_status_var.set` and
  `_later_btn.set_state`) were not wrapped in `try/except`. If called after
  the update dialog was already destroyed, both calls would raise `TclError`
  which Tkinter's `report_callback_exception` would print to stderr. Fixed:
  both calls are now individually wrapped in `try/except Exception: pass`.

- **Output panel `stat()` TOCTOU race** — in `_build_outputs_panel`, the
  `fpath.stat().st_size` call used to produce the file-size label was not
  guarded. If a file was deleted externally between `iterdir()` and `stat()`,
  a `FileNotFoundError` crashed the panel refresh. Fixed: wrapped in
  `try/except OSError`; falls back to `"—"` for the size label.

- **`_running_version()` read stale pip-installed metadata** — the updater
  called `importlib.metadata.version("uacragent")` directly, which reads the
  `.dist-info` from the *last* `pip install`, not the current source. If
  `pyproject.toml` was bumped without re-running `pip install -e .`, the
  updater compared against the wrong baseline. Fixed: `_running_version()` now
  delegates to `uacragent.__version__`, which already has the correct
  `importlib.metadata` + `pyproject.toml`-fallback resolution chain.

- **`__init__.py` hardcoded version fallback** — the bare-source fallback
  `__version__ = "0.3.2"` required manual editing on every release bump,
  creating a second place to update alongside `pyproject.toml`. Fixed: the
  fallback now reads `pyproject.toml` dynamically via regex, so only
  `pyproject.toml` needs to change per release.

### Changed

- **`_safe_rmtree` consolidated into `workspace.py`** — `workspace_manager.py`
  and `vectorstore.py` both contained identical `_safe_rmtree` implementations.
  The canonical version now lives in `workspace.py`; both callsites import from
  there.

- **`_SAFE_ID_RE` no longer re-declared in `dict_to_session()`** — the
  path-traversal guard regex was compiled inline with a local `import re as _re`
  inside `persistence.py:dict_to_session()`. It now imports the already-compiled
  constant from `workspace.py`.

- **`_extract_file_text()` return type** — changed from `str` to
  `tuple[str, str | None]`. Second element is a user-facing warning string on
  extraction failure, or `None` on success. Callers updated accordingly.

- **`workspace_manager.py` import ordering** — `from uacragent.infra.workspace
  import _safe_rmtree` was positioned after `logger = logging.getLogger(__name__)`,
  requiring a `# noqa: E402` linter suppression. Moved above the logger
  assignment so it follows standard module-level import ordering with no
  override needed.

---

## [0.3.2] — 2026-06-02

### Fixed

- **Drag-and-drop broken in standalone built apps** — files dragged onto the
  chat input were silently ignored in PyInstaller-frozen builds. Root cause
  (three layers, all fixed):

  1. *Tcl's `auto_path` scan completed before tkinterdnd2 could register
     itself.* In a frozen build the Tcl interpreter is fully initialised
     (including its initial `pkgIndex.tcl` scan) before Python imports
     `tkinterdnd2`, so `tkinterdnd2._require()`'s `lappend auto_path` call
     arrived too late. Fix: both runtime hooks now set `TCLLIBPATH` before any
     Python code runs. Tcl reads `TCLLIBPATH` at interpreter startup — before
     the first package-index scan — and prepends each listed path to
     `auto_path`, guaranteeing that `pkgIndex.tcl` is found on the very first
     `package require tkdnd` call.

  2. *`CS_LINKER_SIGNED` flag on the macOS dylib prevented loading.* The tkdnd
     dylib from the tkinterdnd2 wheel carries `CS_LINKER_SIGNED`
     (`flags=0x20002`), a signature flag set by Apple's linker at build time.
     macOS refuses `dlopen()` of a linker-signed dylib inside an app bundle
     that was signed separately (even with an ad-hoc signature) — the signing
     contexts are treated as incompatible. Fix: both spec files bundle the
     platform-specific extension directory (dylib and `.tcl` scripts) entirely
     as `datas` to guarantee exact placement at the path `pkgIndex.tcl`
     expects. A post-bundle `codesign --force --sign -` step then re-signs the
     dylib with a plain ad-hoc signature, removing `CS_LINKER_SIGNED`, followed
     by a `codesign --force --deep --sign -` pass to keep the outer bundle
     signature consistent.

  3. *`tkinterdnd2>=0.3` resolves to a Tcl-9-incompatible version.* Newer
     releases of tkinterdnd2 ship `libtcl9tkdnd*.dylib`, compiled against
     Tcl 9. Python 3.13's bundled Tcl is version 8.6; attempting to load a
     Tcl 9 extension under Tcl 8.6 raises a `TclError` silently wrapped as
     "Unable to load tkdnd library." Fix: `requirements.txt` now pins
     `tkinterdnd2==0.4.3`, the last release whose dylib is Tcl-8.6-compatible
     (`libtkdnd2.9.3.dylib`). This pin must be revisited if a future Python
     version upgrades its bundled Tcl to 9.

  The Windows runtime hook uses a three-layer strategy: `TCLLIBPATH`
  (primary), `PATH` prepend (DLL dependency resolution for `LoadLibrary`),
  and `os.add_dll_directory()` (belt-and-suspenders). The macOS runtime hook
  uses two layers: `TCLLIBPATH` (primary) and `DYLD_FALLBACK_LIBRARY_PATH`
  (belt-and-suspenders). Both hooks include a fallback scan that finds the
  correct platform subdirectory even if the naming convention changes in a
  future tkinterdnd2 release.

- **App Settings `×` close button applied live-preview changes permanently** —
  closing the App Settings dialog via the OS window-close button (`×`) called
  Tkinter's raw `destroy()` directly, bypassing the in-dialog Cancel handler.
  This meant any live-preview theme or font-size change the user was exploring
  was silently committed even when they intended to cancel. Fix: the window's
  `WM_DELETE_WINDOW` protocol is now wired to the same `_cancel` callback used
  by the Cancel button, which reverts all live-preview changes before calling
  `_safe_destroy_toplevel`.

- **Session Settings `×` close button raised `TclError`** — closing the
  Session Settings dialog via `×` called raw `destroy()`, which raced with
  widget-command teardown and raised `TclError: can't delete Tcl command`. Fix:
  the window's `WM_DELETE_WINDOW` protocol is now wired to
  `_safe_destroy_toplevel`, consistent with the rest of the dialog teardown
  paths.

- **Drag-and-drop broken for users with spaces in their Windows username** —
  `TCLLIBPATH` was set by bare string concatenation. Tcl parses `TCLLIBPATH` as
  a whitespace-separated list, so a path such as
  `C:\Users\John Smith\AppData\...\tkdnd\win-x64` was split at the space,
  causing the Tcl package scan to look in the wrong directories and
  `package require tkdnd` to fail silently. Fix: the tkdnd path is now
  brace-quoted (`{C:/Users/John Smith/.../win-x64}`) in both runtime hooks
  before being inserted into `TCLLIBPATH`, making it a single list element
  regardless of spaces. Backslashes are also converted to forward slashes
  (Tcl's preferred form) on Windows.

- **Paste attachments not cleaned up on session switch or app close** —
  clipboard-pasted images written to temp files were only deleted after a
  successful send or when the user explicitly removed the attachment chip.
  Switching sessions, creating a new session, or quitting the app while the
  attachment queue was non-empty left the files on disk indefinitely. Fix: a
  new `_discard_pending_attachments()` helper clears the queue and deletes any
  owned temp files; it is called on session switch (when switching to a
  *different* session — re-clicking the active session to reload preserves the
  queue), on new session creation, and on app close.

- **Paste temp images written to OS temp directory** — clipboard-pasted images
  were created via `tempfile.mkstemp()` without a `dir` argument, scattering
  `uacr_paste_*.png` files across the system temp directory (`/tmp`,
  `%TEMP%`). Fix: all paste temp files now land in
  `~/.uacragent/paste_tmp/`, an app-owned directory that is stable regardless
  of the user's custom app data folder setting. A startup sweep deletes any
  files left by a previous crash.

- **Non-paste attachments could be accidentally deleted** — all cleanup paths
  used `Path(path).name.startswith("uacr_paste_")` as the deletion predicate.
  A user file named `uacr_paste_notes.pdf` attached via the + button or
  drag-and-drop would have matched and been deleted from the user's disk. Fix:
  only attachment dict entries explicitly marked `"is_temp_file": True` (set
  only by the `mkstemp` path) are ever deleted; user files are never touched
  regardless of their name.

### Fixed (file-system safety hardening)

- **TOCTOU race in session deletion** — `delete_session()` checked
  `workspace.is_symlink()` once, then called `shutil.rmtree(workspace)` several
  lines later. A concurrent process could have replaced the directory with a
  symlink in that window, redirecting `rmtree` to an arbitrary location on
  disk. Fix: `is_symlink()` is re-checked immediately before `rmtree`; a
  disagreement logs a warning and aborts the deletion.

- **`_atomic_write_text` used a fixed `.tmp` suffix** — two callers writing
  files with the same stem in the same directory (e.g. a hypothetical future
  `session.json` and `session_v2.json`) would share the same `.tmp` path and
  the second write would silently truncate the first. Fix: `_atomic_write_text`
  now uses `tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp",
  delete=False)` to generate a guaranteed-unique sibling temp file.

- **Output panel delete did not guard against symlinks** — the Delete button in
  the Generated Outputs panel called `p.unlink()` with no symlink check. A
  symlink manually placed in the outputs directory would have been removed
  without warning. Fix: `p.is_symlink()` is checked before `unlink()`; symlinks
  raise an `OSError` that surfaces as a user-visible error dialog instead of
  silently removing the entry.

- **Empty temp file leaked when clipboard image save failed** — `mkstemp`
  creates the file before `cb.save()` is called. If `cb.save()` raised an
  exception the empty file was orphaned until the next startup sweep. Fix: the
  except block now deletes `_tmp` before falling through.

- **Paste temp files leaked if background thread failed to start** —
  `_pending_attachments` is cleared before the worker thread starts. If
  `Thread.start()` raised (e.g. OS resource exhaustion), the `finally` block
  inside `_work` never ran and `_tmp_paste_paths` was lost. Fix: `Thread.start()`
  is now wrapped in a try/except that deletes `_tmp_paste_paths` entries and
  restores the busy state on failure.

- **`reset_manifest` swallowed failures silently** — an `OSError` (disk full,
  permission denied) in `reset_manifest` was caught and discarded with no log
  output, making the failure invisible. Fix: the except block now calls
  `_vs_logger.warning(…)`, consistent with `_save_manifest`'s existing
  behaviour.

---

## [0.3.1] — 2026-06-01

### Fixed

- **Fatal crash on window close (`PyEval_RestoreThread: GIL released`)** —
  closing the app while an LLM stream or indexing operation was in-flight caused
  a fatal Python error as the interpreter shut down with a daemon worker thread
  still executing. Fix: `_on_close` now sets `_cancel_event` immediately (so all
  workers stop at the next chunk boundary) and defers `destroy()` by 200 ms via
  `after()`, giving threads time to exit cleanly before the window tears down.

- **`TclError: can't delete Tcl command` on window close** — the elapsed-timer
  ticker re-registered itself via `after()` during `destroy()`'s widget teardown,
  hitting an already-unregistered Tcl command. Fix: the timer is explicitly
  cancelled in `_on_close` before the deferred destroy; `_do_destroy()` also
  catches `TclError` as a last-resort guard.

- **Plain-text paste freezes the app (macOS)** — pasting any plain text into the
  chat input caused a multi-second UI freeze. Root cause: `PIL.ImageGrab.grabclipboard()`
  runs `osascript -e "get the clipboard as «class PNGf»"` synchronously on the
  main thread; on macOS this subprocess can block for several seconds when the
  clipboard holds plain text. Fix: a new `_clipboard_has_image()` helper checks
  for image UTIs via `AppKit.NSPasteboard.types()` (< 1 ms, no subprocess) and
  PIL is only called when image data is actually present.

- **One bad file aborted the entire indexing run** — a corrupted PDF, unsupported
  extension, or encoding error in a single file caused `load_and_split_classified`
  to raise immediately, discarding all other files. Fix: each file is now
  processed inside an individual `try/except IngestError`; failures are logged
  and skipped, and a consolidated error is raised only when every file fails.

- **Non-UTF-8 text files raised a cryptic error** — `TextLoader` uses strict
  UTF-8 and raised `UnicodeDecodeError` for Latin-1 / GBK encoded files. Fix:
  replaced with `Path.read_text(encoding="utf-8", errors="replace")` so
  non-UTF-8 content is loaded with replacement characters rather than crashing.

- **Image-only (scanned) PDFs gave a confusing error** — PDFs with no text
  layer (e.g. scanned documents) produced zero chunks and triggered the generic
  `"No document chunks were created"` error. Fix: after loading, pages that are
  all empty are detected and raise a specific `IngestError` that names the file
  and directs the user to an OCR tool.

- **No large-file guard** — loading a very large file (e.g. 500 MB textbook)
  could exhaust process memory before any chunks were produced. Fix: files over
  300 MB are refused with a clear error before any I/O; files over 100 MB log a
  warning.

- **History summary not sanitised before system-prompt injection** — the LLM-
  generated conversation summary was appended to the system prompt without
  passing through `_sanitise()`, leaving a path for `[TASK:]` patterns surviving
  from earlier turns to reach the prompt. Fix: the summary now has `[TASK:`
  neutralised (via U+2060 word-joiner) before injection, consistent with all
  other user-controlled fields.

- **Attachment filenames not sanitised in system prompt** — file names displayed
  in the `attachments_note` section of the system prompt were injected verbatim.
  A file named `notes [TASK:mock_exam].pdf` would place that pattern in the
  prompt. Fix: each attachment name is now passed through `_sanitise()`.

- **Temp paste images not deleted when removed from queue** — clipboard-pasted
  images were written to `uacr_paste_*.png` temp files. Cleanup ran in the
  `finally` block after each *send*, but if the user removed the attachment
  before sending, the temp file was never deleted. Fix: `_remove_attachment` now
  deletes the temp file immediately when removing a paste attachment.

- **`_runtime_secret_env_vars()` erased non-secret env vars** — `EMBEDDING_PROVIDER`
  and `LOCAL_EMBEDDING_MODEL` were included in the secret-clearance list
  alongside API keys. This caused the embedding provider setting to be silently
  stripped from the child process env during an app-data-folder relaunch, causing
  the relaunched app to revert to the default embedding provider. Fix: only
  actual API keys (`GOOGLE_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`) are
  in the clearance list; `_on_close` now delegates to `_clear_runtime_secrets()`
  instead of duplicating the list.

- **CLI `--workspace-id` bypassed path-safety validation** — the desktop and
  API layers validate `workspace_id` against a safe-character regex, but the CLI
  set `workspace_folder` directly without this check, allowing
  `--workspace-id ../../sensitive` to place session files outside the intended
  `cli_run/` directory. Fix: the CLI now validates against the same
  `^[A-Za-z0-9_-]{1,128}$` pattern and exits with a clear error on failure.

- **API concurrent requests shared a workspace** — two simultaneous `POST /review`
  calls with `workspace_id="default"` wrote to the same `chroma_db/` directory,
  causing SQLite lock collisions. Fix: the `"default"` workspace ID is replaced
  with a per-request UUID; callers who supply an explicit non-default ID retain
  their own workspace.

- **Export `OSError` escaped unwrapped** — `save_markdown`, `save_docx`, and
  `save_pdf` let `OSError` (disk full, permission denied) propagate as a bare
  exception instead of the domain `ExportError` the callers expect. Fix: all
  three functions now wrap OS-level failures in `ExportError` with a
  human-readable "check disk space / permissions" message.

- **Session file picker showed incomplete extension list** — the file-picker
  dialog offered only `.pdf .txt .md .docx .csv`, omitting `.py .js .ts .html
  .htm .xml .json` that the loader already supports. Fix: all supported
  extensions are now listed, grouped into "Code files" and "Web / Data" filter
  entries.

- **History summarisation fired back-to-back with the preceding chat turn** —
  when the session history exceeded the token budget, the trim/summarisation LLM
  call fired immediately after the preceding chat reply with no inter-call delay,
  risking rate-limit errors on Free-tier plans. Fix: `_smart_trim_history` now
  accepts and respects `request_delay` from the active rate tier before invoking
  the summarisation call.

- **`_ls()` silently returned raw key name on missing i18n key** — when a
  localisation table key was absent from both the requested locale and the
  English fallback, the raw key string was returned with no indication anything
  was wrong. Fix: a `WARNING` is now logged with the key name and language.

- **`gpt-4o-search-preview` models incorrectly allowed image attachments** — the
  vision guard was provider-level only; search-preview model variants that do not
  accept multimodal inputs were not excluded. Fix: `_provider_supports_vision()`
  now also checks the model name and returns `False` for any model containing
  `"search-preview"`.

- **Chunk ID collision — file-removal detection tests fixed** — `_files_were_removed()`
  is the mechanism that wipes ChromaDB when files are removed from a session,
  preventing stale chunks (which may share the same content-hash ID as new
  chunks) from persisting across indexing runs.  Three tests that verified this
  behaviour were writing the manifest file in the wrong JSON schema —
  ``{"files": {"doc_type": [paths]}}`` instead of the correct list-of-dicts
  form ``{"files": [{"doc_type": …, "path": …}]}`` — causing a ``TypeError``
  and leaving the detection mechanism completely untested.  The tests are now
  fixed and all three pass, confirming that the collision-avoidance wipe path
  works as intended.

- **`test_api_keys_not_persisted` test fixed** — imported the nonexistent
  function ``session_to_dict``; replaced with the correct ``save_session`` +
  raw JSON file assertion pattern that exercises the actual persistence layer.

### Added

- **Comprehensive test suite** — 180 new tests across 8 new files covering
  `rate_tiers`, `doc_priorities`, `reasoning`, `session` / `_HistoryStore`,
  `persistence` (full serialisation), `vectorstore` (manifest, `chroma_is_current`,
  `WeightedDocTypeRetriever`), CSV ingestion, pipeline utilities (effort config,
  `_expand_user_prefs`, cancel / partial-result paths), and settings env-var
  handling. Total: **426 tests, all passing**.

---

## [0.3.0] — 2026-05-31

### Added

- **Paste-to-attach** — files and images can now be pasted directly into the
  chat input field (Cmd+V / Ctrl+V) to attach them, consistent with using the
  `+` button or drag-and-drop. Supported types: PDF, DOCX, plain text, Markdown,
  code files, CSV, JSON, XML, HTML, and common image formats.

- **Windows installer** — an Inno Setup script (`UACRAgent_installer.iss`) is
  now included for building a proper Windows installer, providing a smoother
  Windows installation experience than the raw zip distribution.

### Fixed

- **Paste-to-attach format preservation (macOS)** — files pasted from Finder
  were being saved and attached as PNG images instead of their original format.
  Root cause: PIL's `grabclipboard()` on macOS runs
  `osascript "get the clipboard as «class PNGf»"`, which coerces any clipboard
  content — including a PDF file's Finder icon — to PNG before returning.
  Fix: the pasteboard's `NSFilenamesPboardType` is now read directly via the
  AppleScript/Obj-C Foundation bridge (`use framework "Foundation"`) before PIL
  is invoked. This requires no PyObjC dependency and works on all supported
  macOS versions.

- **Paste-to-attach format preservation (Windows)** — files pasted from
  Explorer were returning zero results from the file-list reader, causing
  fallthrough to PIL which may return a thumbnail image. Root cause:
  `DragQueryFileW` was passed a raw locked memory pointer from `GlobalLock`
  instead of the HDROP handle returned by `GetClipboardData`. Fix: the
  `GlobalLock` / `GlobalUnlock` calls are removed; the HDROP handle is now
  passed directly to `DragQueryFileW` as the Windows API requires.

- **Temp paste image cleanup** — raw pasted images (screenshots, browser image
  copies) are saved to a `uacr_paste_*.png` temp file so the LLM can read them.
  These files were previously never deleted. They are now removed in a `finally`
  block after each send, regardless of whether the LLM call succeeded, failed,
  or was cancelled.

- **Settings and search icon rendering on Windows** — the `⚙` gear symbol in
  the "App Settings" and "Session Settings" button labels now renders cleanly on
  Windows. Root cause: `TkDefaultFont` on Windows maps to Segoe UI, which lacks
  the Miscellaneous Symbols Unicode block that `⚙` (U+2699) belongs to. Fix:
  `Segoe UI Symbol` — which ships with every Windows version and fully covers
  that block — is now selected automatically on Windows for the icon glyph.

- **Sidebar search icon on Windows** — the `🔍` emoji in the sidebar search
  box is replaced with a canvas-drawn magnifying glass (oval + diagonal line via
  `draw_search_icon()`). The drawn icon renders crisply at all sizes and DPI
  settings on every platform and avoids the emoji rendering inconsistencies that
  affected `TkDefaultFont` on Windows.

---

## [0.2.0] — 2026-05-30

### Added

- **Hover tooltips on toolbar buttons** — hovering over the Web Search (🌐) or
  Attach (+) button for 600 ms now shows a compact tooltip. Tooltips respect the
  active colour theme, scale with the font-size setting in App Settings, and
  follow the cursor correctly on multi-monitor setups including secondary
  displays with negative screen coordinates.

- **Attachment chips in chat history** — files and images attached to a message
  are now shown as icon + filename chips inside the user's chat bubble. Chips
  are preserved across session reloads (attachment name, MIME type, and file
  path are stored in `HumanMessage.additional_kwargs` and round-trip through the
  session persistence layer).

- **Clickable attachment chips** — clicking an attachment chip in either the
  pre-send input strip or a historical chat bubble opens the file in the OS
  default application (Finder / Explorer / xdg-open). Only the trailing `×`
  token removes an attachment from the queue.

### Changed

- **Responsive cancellation** — pressing Cancel now exits within a fraction of
  a second for all pipeline stages. The initial conversational LLM call, the
  plan-generation structured call, every section write, and the exam-paper
  generation step are all interruptible. Previously, the background thread
  could block for the full duration of the remaining request (up to a minute
  for large document sets or slow models).

- **Message preserved on cancel** — the user's request is now kept in session
  history when a generation is cancelled, so conversation context is not
  silently lost. The AI reply is discarded; only the human turn is retained.

- **DOCX attachment extraction** — Word documents attached in chat now use
  `python-docx` as the primary extractor (handles a wider range of real-world
  `.docx` files including complex formatting and embedded tables) with
  `Docx2txtLoader` kept as an automatic fallback. Previously a single library
  failure surfaced as a visible error to the LLM with no retry.

### Fixed

- **False-positive generation trigger** — sending a test message or
  image-visibility check (e.g. "Test, test, can you see the image?") no longer
  accidentally triggers study-plan generation. A two-layer guard — a tightened
  system-prompt instruction list and a narrow code-level blocklist for
  unambiguous non-generation patterns — prevents the LLM from firing the
  pipeline on obviously conversational messages while leaving all natural-
  language generation requests fully intact.

- **Tooltip placement on secondary monitors** — tooltips now anchor to
  `winfo_pointerx/y` (true multi-monitor screen coordinates) instead of the
  widget's root coordinates. The previous `winfo_screenwidth/height` clamping
  used only the primary display's dimensions, forcing tooltips onto the primary
  screen whenever the app window was on any other display.

- **Tooltip rendering on macOS** — the macOS native `help` window level
  (`::tk::unsupported::MacWindowStyle style … help noActivates`) is now applied
  before `overrideredirect`, ensuring tooltips float above all application
  content layers on macOS rather than being clipped by sibling widgets.

---

## [0.1.2]

### Added

- **Windows standalone build** — UACRAgent is now available as a standalone
  `.exe` build for Windows 10 / 11.

- **OpenAI conversation storage opt-out** — UACRAgent now sends `store=false`
  on every OpenAI request, opting out of the Responses API's default
  conversation logging on the OpenAI platform dashboard. Users who want to
  allow storage can re-enable it in App Settings → Privacy → Provider data
  storage, or by setting `OPENAI_STORE_RESPONSES=true` in `.env`.

### Fixed

- **Windows path-separator mismatch** — Tkinter's file dialog returns
  forward-slash paths on Windows while `Path` uses backslashes; the exam-info
  file containment check now uses `Path.is_relative_to()`, which is
  separator-agnostic.

- **Windows file-locking on session delete** — the ChromaDB SQLite connection
  is now explicitly released before session deletion, preventing
  `PermissionError` from leaving orphaned files on disk.

- **Font-size setting not propagating** — the App Settings font-size control
  now correctly scales all UI text including session list items, the placeholder
  label, the drag-and-drop overlay, and the thinking indicator.

- **App Settings Cancel button** — Cancel now correctly reverts the OpenAI
  storage checkbox when the user made a change and then cancelled.

- **Missing i18n strings** — the App Settings "Browse…" button and folder
  picker title are now localised for Simplified Chinese users. All 224 UI
  strings are present and consistent in both English and Simplified Chinese.

### Security

- User-entered text fields (course name, extra instructions, exam info, etc.)
  are now sanitised before injection into the LLM system prompt, preventing
  `{`/`}` brace errors and `[TASK:]` prompt-injection via crafted text.

- `workspace_id` values loaded from session files are validated against a
  safe-character allowlist, preventing path-traversal via tampered session data.

- `llm_provider` loaded from session files is validated against a known
  provider allowlist.

- File copy operations now refuse to follow symlinks.

- Collision-avoidance loops in file operations are capped at 1 000 iterations.

---

## [0.1.1]

### Added

- **Windows standalone build** — UACRAgent is now available as a standalone
  build on Windows 10 / 11 (`UACRAgent.exe`). Download
  `UACRAgent-windows-x64.zip`, extract it, and run the `.exe` from the
  extracted folder (keep all bundled files together).

### Fixed

- **Windows path-separator issue** — resolved a path-separator mismatch
  affecting exam info file handling on Windows.

- **Windows file-locking on session delete** — fixed a file-locking issue that
  could leave orphaned files when deleting a session while ChromaDB had the
  workspace open.

---

## [0.1.0]

Initial desktop release of UACRAgent. This version establishes the core
desktop-first workflow and marks the first public-facing GUI release.

### Added

- **Persistent desktop chat assistant** — session-aware conversational
  interface for studying from course materials with local state saved across
  app restarts.

- **RAG pipeline** — full retrieval-augmented generation pipeline: ingest →
  classify → chunk → embed (Chroma) → retrieve → generate.

- **Document-type-aware splitting** — specialized chunking strategies for
  syllabus, lecture notes, textbooks, assignments, past exams, and general
  course materials.

- **Multi-provider LLM support** — Gemini, OpenAI, and DeepSeek for chat,
  planning, and writing.

- **Multiple embedding options** — Gemini embeddings, OpenAI embeddings, and
  local on-device embeddings via the built-in ONNX backend (no API key
  required).

- **Study-artefact generation** — Review Summary, Practice Booklet, Mock Exam,
  and Exam Prediction modes, triggerable in natural language or via
  quick-action buttons.

- **Session management** — persistent per-session workspaces with isolated
  vector stores, outputs, and uploaded file copies; fast-attach path reuses the
  saved index when the file set has not changed.

- **Multiple interfaces** — Desktop GUI (primary), interactive CLI, and a local
  FastAPI API (`GET /health`, `POST /review`, `POST /review/simple`).

- **Export formats** — canonical Markdown output with optional DOCX and PDF
  export from the desktop GUI.

- **macOS standalone build** — code-unsigned standalone `.app` build for
  macOS. Windows build planned for a future release.

---

## [0.0.0]

Initial alpha release. Establishes the foundational RAG pipeline and
generation modes.

### Added

- **RAG pipeline** — multi-stage pipeline: ingest course materials → classify
  by document type → apply type-specific chunking → embed into a local Chroma
  vector store → plan output structure via LLM → retrieve material
  section-by-section → generate structured exam-prep content.

- **Document ingestion** — PDF, DOCX, TXT, Markdown, CSV, and common
  code/text formats.

- **Structured course context** — accepts course name, university, department,
  course code, professor, semester, exam duration, and exam info sheet.

- **Four generation modes** — Review Summary, Practice Booklet, Mock Exam, and
  Exam Prediction.

- **Document-type classification** — specialized handling for syllabus, lecture
  notes, textbooks, assignments, past exams, and other materials.

- **Multiple interfaces** — Desktop GUI, CLI, and FastAPI API
  (`GET /health`, `POST /review`, `POST /review/simple`).

- **Export** — canonical Markdown output with optional DOCX and PDF export via
  the desktop GUI.

- **Configurable runtime** — retry settings and request-delay controls to
  manage API rate limits.

- Platform support: macOS, Windows, Linux (Python 3.10+).
- Google Gemini for planning, writing, and embeddings.
- Released under the MIT License.
