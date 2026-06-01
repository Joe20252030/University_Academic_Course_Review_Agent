# Changelog

**Project website:** <https://joe20252030.github.io/University_Academic_Course_Review_Agent/>  
**Repository:** <https://github.com/Joe20252030/University_Academic_Course_Review_Agent>

All notable changes to UACRAgent are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
