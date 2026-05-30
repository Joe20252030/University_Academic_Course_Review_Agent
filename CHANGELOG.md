# Changelog

**Project website:** <https://joe20252030.github.io/University_Academic_Course_Review_Agent/>  
**Repository:** <https://github.com/Joe20252030/University_Academic_Course_Review_Agent>

All notable changes to UACRAgent are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
