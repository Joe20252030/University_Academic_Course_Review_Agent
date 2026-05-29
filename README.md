# University Academic Course Review Agent (UACRAgent)

Study from course documents with a grounded academic assistant, and generate
review materials when you need them through a persistent desktop chat workflow.

- Ingest course materials (PDF, DOCX, CSV, and common text/code formats such as TXT, Markdown, JSON, HTML, XML, and source files)
- Classify documents by type for optimized processing
- Chunk documents using type-specific multi-stage splitting strategies
- Embed into a local Chroma vector store
- Retrieve context with task-aware weighting across document types
- Chat with an LLM in a session-aware study-assistant workflow
- Ask grounded course questions and get guided review help from uploaded materials
- Generate structured study artefacts such as review summaries, mock exams, and practice booklets when requested
- Save canonical generated output as Markdown, with optional DOCX/PDF export in the desktop GUI
- Persist desktop sessions, settings, and chat history across app restarts

## License

This project is released under the **MIT License**. See [LICENSE](LICENSE).

## Privacy & Data Usage

UACRAgent is designed so that most working data stays on your machine, but it
can still send selected content to third-party model providers depending on how
you configure it.

What is stored locally:

- Desktop session state is saved on disk so you can reopen sessions later.
- Session data includes course settings, selected file paths, chat history,
  chosen provider/model settings, and session UI preferences.
- Session state is stored in `<workspace>/.uacragent/session.json`.
- Retrieved document indexes are stored locally in
  `<workspace>/.uacragent/chroma_db/`.
- Generated outputs are stored locally in `<workspace>/.uacragent/outputs/`.
- When files are copied into a workspace, they are stored under
  `<workspace>/.uacragent/uploads/`.
- Local embedding models are cached under `<app_data_dir>/models/`.
- In frozen standalone app builds, the ONNX local embedding model is also kept
  inside `<app_data_dir>/models/chroma/onnx_models/`.

What is not written to session files:

- Desktop-entered API keys are kept in process memory only.
- The session persistence layer intentionally does not write provider API keys
  to disk.

What may be sent to external providers:

- Chat requests may send your message, selected chat attachments, course
  metadata, recent chat history, and retrieved document excerpts to the active
  LLM provider.
- Document-generation requests may send course metadata, planning context,
  retrieved document chunks, and generation instructions to the active LLM
  provider.
- If you use cloud embeddings (`gemini` or `openai`), document chunks are also
  sent to that embedding provider during indexing.
- If you enable provider-backed web search or file-attachment features in the
  desktop chat, the relevant request content is also handled by the selected
  provider.

Provider and deployment notes:

- If you want to minimize cloud data sharing, use `EMBEDDING_PROVIDER=local`.
  This still leaves chat/generation requests going to the selected LLM
  provider unless you also choose a different runtime architecture outside the
  current app.
- Local embeddings download their model backend on first use, then reuse the
  local cache afterward.
- On first launch, the desktop GUI shows a privacy notice that must be accepted
  before use. You can reopen the notice later from App Settings, and the
  session settings dialog also shows a provider-specific privacy reminder and
  privacy-policy link.
- The FastAPI interface accepts absolute file paths. Without
  `UACRAGENT_ALLOWED_BASE_DIR`, a local API server can read any absolute
  existing file path supplied in a request. The current API is intended for
  local trusted use only; if you still want an extra filesystem safety fence,
  set `UACRAGENT_ALLOWED_BASE_DIR`.
- Deleting a session removes the `<workspace>/.uacragent/` bundle. Original
  source files outside that folder are not deleted.

You are responsible for choosing providers, deployment settings, and input
documents that meet your own privacy, institutional, and regulatory
requirements.

## Disclaimer

UACRAgent is an educational study-assistance tool. It can help summarize
materials, answer grounded questions, and generate review artefacts, but it may
still produce incorrect, incomplete, outdated, or misleading content.

UACRAgent is an independent open-source project. It is not affiliated with,
endorsed by, or officially connected to OpenAI, Google, DeepSeek, or any 
university, school, examination body, or educational institution.

Please keep in mind:

- Generated summaries, mock exams, predictions, and explanations are study aids,
  not official course materials.
- The app does not guarantee exam accuracy, topic coverage, grading alignment,
  or factual correctness.
- You should verify important claims, formulas, deadlines, policies, and exam
  expectations against your instructor, syllabus, textbook, and other official
  sources.
- Do not rely on this project as a substitute for professional, legal,
  medical, financial, or institutional advice.
- If you upload sensitive or confidential documents, review your provider and
  deployment choices carefully before use.
- Third-party LLM and embedding providers may apply their own privacy policies,
  retention practices, and terms of service when processing requests sent from
  this app.

## Interfaces

The project currently has three user-facing interfaces:

- **Desktop GUI**: the primary interface, now built as a persistent conversational assistant with session management
- **CLI**: interactive conversational terminal interface that indexes documents once, then answers questions and generates study documents on request
- **FastAPI API**: programmatic one-shot document generation

## Task Types

The assistant supports four distinct generated output modes:

| Task                 | Description                                                                                                                      |
|----------------------|----------------------------------------------------------------------------------------------------------------------------------|
| **Review Summary**   | Comprehensive review with key concepts, definitions, tips, and sample questions                                                  |
| **Practice Booklet** | Structured collection of practice problems (easy/medium/hard) with solution key                                                  |
| **Mock Exam**        | Realistic exam paper with point allocations and a separate answer key                                                            |
| **Exam Prediction**  | **Two-part output:** Part A — topic-by-topic prediction analysis (confidence level, reasoning, study approach, sample questions);|
|                      | Part B — a complete predicted exam paper with realistic questions, mark allocations, and a full answer key / marking guide       |

Each task uses dedicated planner and writer prompts tuned for its output format.

## Model Providers

The project supports multiple LLM providers for chat, planning, and writing:

| Provider | Use Cases                           | Desktop Chat Extras                  | Required Key       |
|----------|-------------------------------------|--------------------------------------|--------------------|
| Gemini   | Chat, planning, writing, embeddings | Web search + file attachments        | `GOOGLE_API_KEY`   |
| OpenAI   | Chat, planning, writing, embeddings | Web search + file attachments        | `OPENAI_API_KEY`   |
| DeepSeek | Chat, planning, writing             | Standard chat only                   | `DEEPSEEK_API_KEY` |

Model note:
- Desktop chat attachment controls are gated by the active provider and model.
  For example, OpenAI `*-search-preview` models support built-in web search but
  disable the upload button because they do not accept file/vision inputs.

## Embedding Providers

Document retrieval embeddings are configured independently from the chat/writer
LLM provider:

| Provider | Use Cases                                  | Requirements                            |
|----------|--------------------------------------------|-----------------------------------------|
| Gemini   | Cloud embeddings                           | `GOOGLE_API_KEY`                        |
| OpenAI   | Cloud embeddings                           | `OPENAI_API_KEY`                        |
| Local    | On-device embeddings                       | No API key; first use downloads a model |

The desktop GUI exposes all three embedding options. Local embeddings are free
to run after the model has been downloaded and cached.

Backend note:
- In source installs, `EMBEDDING_PROVIDER=local` uses the
  `sentence-transformers` / HuggingFace stack.
- In frozen standalone app builds, local embeddings use Chroma's ONNX-based
  `all-MiniLM-L6-v2` path instead of the PyTorch stack for packaging
  reliability, but the downloaded model still stays inside `<app_data_dir>/models/`.

## Exam Types

Users specify the kind of exam they are preparing for:

| Exam Type     | Description                        |
|---------------|------------------------------------|
| **Quiz**      | Short, focused assessment          |
| **Midterm**   | Mid-semester examination           |
| **Final**     | End-of-semester comprehensive exam |
| **Term Test** | In-term test                       |
| **Other**     | Custom or unspecified              |

The exam type influences prompt behavior — a quiz review is concise and focused while a final review is comprehensive.

## Course Information Fields

When generating output you can supply context about the course. The **Course Name is required**; all other fields are optional but improve the quality and relevance of the output.

| Field              | Required | Example                                                         |
|--------------------|----------|-----------------------------------------------------------------|
| **Course Name**    | Yes      | `Introduction to Algorithms`                                    |
| University         | No       | `University of Toronto`                                         |
| Major / Department | No       | `Computer Science`                                              |
| Course Code        | No       | `CSC263`                                                        |
| Professor          | No       | `Dr. Jane Smith`                                                |
| Semester           | No       | `Fall 2024`                                                     |
| Exam Duration      | No       | `2 hours` or `90 minutes`                                       |
| Exam Info Sheet    | No       | `Closed book. One formula sheet allowed. Topics: chapters 1-6.` |

All fields are passed to every planner and writer prompt, so the LLM can tailor content to the specific course and context. The **Exam Duration** and **Exam Info Sheet** fields are especially useful for generating realistic mock exams and practice booklets that match the actual exam constraints.

Interface note:
- The desktop GUI accepts an exam info sheet file from the Session Settings dialog.
- When the desktop exam info sheet is changed or cleared later, the old
  workspace-local copied file is cleaned up automatically.
- The API accepts `exam_info` as plain text in the request body.
- The current CLI does not expose a dedicated exam-info argument.

## Document Types & Splitting Strategies

Each document type uses a multi-stage splitting pipeline optimized for its structure:

| Type              | Splitting Strategy                                                                | Final Chunk Size |
|-------------------|-----------------------------------------------------------------------------------|------------------|
| **Textbook**      | Markdown header split (chapter/section/subsection) then recursive character split | 1500             |
| **Syllabus**      | Markdown header split (section/subsection) then recursive character split         | 800              |
| **Lecture Notes** | Sentence-aware recursive split (preserves slide bullet points)                    | 1000             |
| **Past Exam**     | Question-boundary regex split (Q1, 1., Part A, (a), etc.) then recursive split    | 500              |
| **Assignment**    | Problem-boundary regex split (Problem/Exercise/Task headers) then recursive split | 600              |
| **Other**         | Standard recursive character split                                                | 1000             |

Multi-stage pipelines feed each stage's output into the next. For example, a textbook
PDF is first split on `#`/`##`/`###` markdown headers to isolate chapters and sections,
then each section is recursively split into retrieval-sized chunks. Header-based
metadata (chapter, section, subsection) is preserved on every chunk.

## Requirements

- Python 3.10+
- At least one LLM API key for generation:
  - Google Gemini, or
  - OpenAI, or
  - DeepSeek
- One embedding option for retrieval:
  - Google Gemini embeddings with `GOOGLE_API_KEY`, or
  - OpenAI embeddings with `OPENAI_API_KEY`, or
  - local on-device embeddings with no API key

Notes:

- Running the pipeline will make paid model requests (LLM + embeddings).
- DeepSeek can be used for chat/planning/writing together with either cloud
  embeddings or local embeddings.
- Local embeddings download their model backend on first use, then run from the
  local cache afterward.
- Source installs use `sentence-transformers` for local embeddings.
- Frozen app builds use Chroma ONNX for local embeddings.
- In the current standalone build, only `all-MiniLM-L6-v2` is supported for
  free local embeddings.
- Standalone app builds also rely on `onnxruntime` and `tiktoken`, which are
  listed in `requirements.txt`.
- Frozen app builds download the ONNX local embedding model into
  `<app_data_dir>/models/chroma/onnx_models/` on first use.

## Install

1) Create and activate a virtual environment

- `python3 -m venv .venv`
- macOS/Linux: `source .venv/bin/activate`
- Windows PowerShell: `.\.venv\Scripts\Activate.ps1`
- Windows `cmd.exe`: `.\.venv\Scripts\activate.bat`
- If PowerShell blocks activation, run:
  `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
  and then `.\.venv\Scripts\Activate.ps1`

2) Install dependencies and the package

- `pip install -r requirements.txt`
- `pip install -e .`

The editable install is recommended because this repository uses a `src/`
layout. Without it, `python -m uacragent` will not resolve unless you
manually set `PYTHONPATH=src`.

### Windows quick setup

For a normal Windows source install after cloning from GitHub:

```powershell
git clone <repo-url>
cd UACRAgent
py -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
copy .env.sample .env
```

Then edit `.env` and set the provider/API keys you want before running the
desktop app, CLI, or API.

### Standalone App Builds

The repository also includes PyInstaller spec files for building standalone
desktop app distributions:

- macOS: `UACRAgent_mac.spec`
- Windows: `UACRAgent_win.spec`

Typical build setup:

- Install the normal project dependencies first.
- Install PyInstaller separately:
  - `pip install pyinstaller`
  - if you build with Python 3.10, also install `tomli`

Typical build commands:

- macOS: `pyinstaller UACRAgent_mac.spec`
- Windows: `pyinstaller UACRAgent_win.spec`

Expected outputs:

- macOS: `dist/UACRAgent.app`
- Windows: `dist/UACRAgent/` containing `UACRAgent.exe` and bundled files

Build note:

- Frozen standalone builds use the ONNX local embedding path rather than the
  `sentence-transformers` / PyTorch stack for packaging reliability.

### Opening unsigned builds

The standalone builds are not code-signed or notarized. Your operating system
will block the app on first launch — this is expected behaviour for unsigned
third-party software. You only need to do this once per installation.

**macOS — Gatekeeper**

The first time you open `UACRAgent.app`, macOS will show:
*"UACRAgent cannot be opened because the developer cannot be verified."*

To allow it:

1. Right-click (or Control-click) `UACRAgent.app` and choose **Open**
2. Click **Open** in the confirmation dialog

Alternatively: open **System Settings → Privacy & Security**, scroll to the
blocked-app notice at the bottom, and click **Open Anyway**.

**Windows — SmartScreen**

The first time you run `UACRAgent.exe`, Windows will show:
*"Windows protected your PC."*

To allow it:

1. Click **More info**
2. Click **Run anyway**

Note: code signing and notarization are planned for a future release. Until
then, these one-time manual steps are required for standalone builds downloaded
from GitHub Releases.

## Configure

### API Keys

Create a `.env` file (copy from `.env.sample`) and set the provider key(s) you
want to use:

```env
GOOGLE_API_KEY=your-google-api-key-here
# OPENAI_API_KEY=your-openai-api-key-here
# DEEPSEEK_API_KEY=your-deepseek-api-key-here
```

`.env` lookup behavior by interface:

- Desktop GUI: reads `<app_data_dir>/.env` first, then falls back to the
  current working directory `.env`.
- CLI: reads `<app_data_dir>/.env` first, then falls back to the current
  working directory `.env`.
- API server: currently reads the current working directory `.env`.

For the default app data directory, `<app_data_dir>` is `~/.uacragent/` unless
you changed it in the desktop app settings.

Recommended locations:

- Desktop GUI / CLI: put `.env` in `<app_data_dir>/` if you want the app to
  find the same keys regardless of the directory you launch it from.
- API server: put `.env` in the server's current working directory.

Official API platform / key-management pages:

- OpenAI: [platform.openai.com](https://platform.openai.com/)
- Gemini / Google AI Studio: [aistudio.google.com](https://aistudio.google.com/)
- DeepSeek: [platform.deepseek.com](https://platform.deepseek.com/)

Desktop GUI users can also enter keys directly in the settings window at
runtime. Keys entered there are kept in process memory only and are not written
to session files.

Provider behavior:

- `gemini` uses `GOOGLE_API_KEY`
- `openai` uses `OPENAI_API_KEY`
- `deepseek` uses `DEEPSEEK_API_KEY`

Embedding configuration:

- `EMBEDDING_PROVIDER=gemini` uses `GOOGLE_API_KEY`
- `EMBEDDING_PROVIDER=openai` uses `OPENAI_API_KEY`
- `EMBEDDING_PROVIDER=local` uses a local on-device embedding backend with no API key

For local embeddings, you can choose the downloaded model with
`LOCAL_EMBEDDING_MODEL` in source installs. Frozen app builds currently support
only one built-app local model:

- `all-MiniLM-L6-v2` uses the built-in ONNX backend, downloaded into
  `<app_data_dir>/models/chroma/onnx_models/`

> Security note: API key fields are excluded from `Settings` repr output, and
> the desktop session persistence layer intentionally does not write API keys to disk.

Startup note:

- The desktop app and API server now log a warning when they detect environment
  variable names that look like UACRAgent settings but are misspelled, such as
  a typo in `GOOGLE_API_KEY` or `LLM_PROVIDER`.

### Other settings

Optional overrides (see defaults in [src/uacragent/infra/settings.py](src/uacragent/infra/settings.py)):

```
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.5-flash
EMBEDDING_PROVIDER=gemini
EMBEDDING_MODEL=gemini-embedding-001   # Gemini only — ignored for OpenAI or local
LOCAL_EMBEDDING_MODEL=all-MiniLM-L6-v2
RETRIEVER_K=8
RATE_TIER=free
OPENAI_STORE_RESPONSES=false
```

**OpenAI conversation storage (`OPENAI_STORE_RESPONSES`):**

OpenAI's Responses API (used by newer models such as GPT-4o and later) stores
every request on the OpenAI platform dashboard by default. UACRAgent sets
`store=false` on every request to opt out and protect privacy. Set
`OPENAI_STORE_RESPONSES=true` only if you want OpenAI to retain your
conversations (e.g. for fine-tuning or evals purposes). This setting can also
be toggled without a restart from **App Settings → Privacy → Provider data
storage**. Has no effect on Gemini or DeepSeek (those providers do not expose
a per-request storage opt-out in their APIs).

API-only optional hardening:

```env
UACRAGENT_ALLOWED_BASE_DIR=/absolute/path/that/api/uploads/must/live/under
```

When `UACRAGENT_ALLOWED_BASE_DIR` is set, the FastAPI server rejects any
requested source file path outside that directory tree.

#### Request Frequency / Rate Limiting

Sections are written **sequentially** (one at a time) to avoid overwhelming the
API. The app now uses a named `RATE_TIER` by default, which maps to concrete
delay/retry settings:

| Tier        | Delay | Retries | Base Retry Delay | Typical Use              |
|-------------|-------|---------|------------------|--------------------------|
| `free`      | `6.0` | `4`     | `20.0`           | Free and trial plans     |
| `standard`  | `0.5` | `3`     | `8.0`            | Entry paid plans         |
| `pro`       | `0.1` | `2`     | `3.0`            | Higher paid tiers        |
| `unlimited` | `0.0` | `1`     | `2.0`            | Very high-capacity plans |

If you prefer raw numeric overrides, clear `RATE_TIER` and then set
`LLM_REQUEST_DELAY`, `LLM_MAX_RETRIES`, and `LLM_RETRY_BASE_DELAY` directly.

Current raw-setting defaults:

| Variable               | Default | Description                                                                                      |
|------------------------|---------|--------------------------------------------------------------------------------------------------|
| `LLM_REQUEST_DELAY`    | `6.0`   | Seconds to wait after each LLM call completes before starting the next                           |
| `LLM_MAX_RETRIES`      | `3`     | Max retry attempts on transient 503/429/quota errors (keep low — retries generate more requests) |
| `LLM_RETRY_BASE_DELAY` | `15.0`  | Initial backoff delay in seconds before the first retry (doubles each attempt, capped at 60 s)   |

Note: these raw values are only effective when `RATE_TIER` is explicitly cleared
(`RATE_TIER=`). When `RATE_TIER` is set to a named tier (the default is `free`),
the tier's own values take precedence — for example, `free` sets `LLM_MAX_RETRIES`
to `4`, not the raw default of `3`.

## Run (Desktop GUI)

- `python -m uacragent --gui`
- `python -m uacragent` (launches the GUI when no file arguments are given)
- `python -m uacragent.ui.desktop.app`

The GUI lets you:
- Create, rename, delete, and reopen persistent study sessions
- Choose an LLM provider (`gemini`, `openai`, or `deepseek`) and model per session
- Choose an API plan tier (`Free`, `Standard`, `Pro`, `Unlimited`) to match provider rate limits
- Enter provider API keys in the settings dialog when they are not already set in `.env`
- Choose an embedding provider (`gemini`, `openai`, or free local embeddings`)
- Pick a free local embedding model when using on-device embeddings in a source install
- Enter a **course name** and optional course details
- Add files to different document type categories (Syllabus, Lecture Notes, etc.)
- Search and filter saved sessions from the sidebar search bar
- Choose exam settings and export format
- Choose per-message effort level (`low`, `medium`, `high`) for chat and generated outputs
- Choose a generation reasoning mode in chat: `Quick Review` for faster single-pass output or `Deep Analysis` for topic extraction plus critic refinement on generated study documents
- Pick a custom workspace folder before the first **Apply**, or let the app auto-create one
- Use **Apply** to commit setting changes and re-index with the updated session configuration
- Chat with the assistant about the course material
- Toggle provider-backed web search for the next message when supported by the active provider
- Attach supported files to chat messages, including drag-and-drop onto the chat area when desktop drag-and-drop support is available
- Use quick actions to generate a Review Summary, Practice Booklet, Mock Exam, or Exam Prediction
- Open generated outputs directly from the chat transcript
- Cancel an in-flight indexing or chat request from the main panel
- Open global app settings to change color mode, font size, language (`Auto`, `en`, or `zh_CN`), the shared app data directory (see [Changing the App Data Folder](#changing-the-app-data-folder) before doing so), and provider data-storage preferences (opt out of OpenAI's server-side conversation logging)
- Use the selected desktop language to steer assistant replies and generated document headings in English or Simplified Chinese
- Review the first-launch privacy notice and reopen it later from App Settings when needed

Works on macOS, Windows, and Linux.

Desktop note:
- File drag-and-drop in the chat area uses `tkinterdnd2` when the Tk extension
  is available. The desktop app still works without it; only drag-and-drop is
  disabled in that case.
- The desktop chat pane currently exposes both depth controls: `effort level`
  changes retrieval/context size for each turn, while `reasoning mode` changes
  the document-generation pipeline used after a chat-triggered quick action.

When you reopen an existing desktop session from the sidebar, the app first
tries a fast attach path. If the saved Chroma index and indexed-file manifest
still match the current file set, it reuses the existing retriever without
re-embedding or making new embedding API calls. A full re-index runs when the
files changed, the index is missing, or you click **Apply** to force current
settings to take effect. On this fast path the session becomes ready silently,
without adding a new "documents indexed" notice to the chat transcript.

## Detailed Use Instructions

### Desktop GUI: Recommended workflow

For most users, the desktop GUI is the easiest way to use the project.

1. Launch the app with `python -m uacragent --gui` or simply `python -m uacragent`.
2. Read and accept the privacy notice shown on first launch.
3. Create a new session from the left sidebar.
4. Open **Settings**.
5. Enter a **Course Name**. This is the only required course field.
6. Choose your LLM provider and model.
7. Add the matching API key in the settings dialog if it is not already loaded
   from `.env`.
   For repeat desktop use, placing `.env` in `<app_data_dir>/` is usually the
   most convenient setup.
8. Review the provider privacy reminder in Settings if you are working with sensitive course material.
9. Choose an embedding provider:
   - `gemini` or `openai` if you want cloud embeddings
   - `local` if you want free on-device embeddings
   - in source installs, `local` uses `sentence-transformers`
   - in frozen app builds, `local` supports `all-MiniLM-L6-v2` via the ONNX local path
10. Add course files into the appropriate document buckets:
   - syllabus
   - lecture notes
   - textbook
   - assignment
   - past exam
   - other
11. Optionally fill in:
   - university / major / course code / professor / semester
   - exam type / exam format / exam duration
   - extra instructions
   - exam information sheet file
   - export format
12. Optionally choose a custom workspace folder before the first **Apply**.
13. Click **Apply**.

What **Apply** does:

- commits the current session settings
- locks in the workspace folder for that session
- saves the session to disk
- copies uploaded files into the session workspace when needed
- keeps the exam info sheet self-contained inside the workspace and removes old
  copied exam-info files when that field is changed or cleared later
- builds or refreshes the Chroma index
- makes the current provider / embedding / model settings take effect

After indexing finishes, you can use the session in two main ways:

- Ask normal study questions in chat, for example:
  - `Explain the most important topics from these lecture notes.`
  - `What should I focus on for the final?`
  - `Summarize the difference between DFS and BFS from the uploaded materials.`
- Generate study documents either:
  - by pressing a quick-action button, or
  - by asking naturally in chat, for example `Generate a review summary for this course.`

Useful desktop controls:

- `Effort level` changes retrieval/context depth for each turn.
- `Reasoning mode` changes the generation pipeline depth for study-document tasks.
- `Web search` is only available for providers that support it.
- `File attachments` are available only when the active provider/model supports file inputs. Unsupported image/file uploads are disabled in the UI.
- `Cancel` stops an in-flight indexing or chat task.
- `Language` in App Settings supports `Auto`, English, and Simplified Chinese.

Reopening sessions:

- Reopen a saved session from the sidebar.
- If the file set and saved Chroma index still match, the app reuses the existing retriever without re-embedding.
- If files changed, or you click **Apply**, the app performs a full re-index.

### Desktop GUI: Best practices

- Put files into the most accurate document type bucket you can. Retrieval quality is better when syllabi, lecture notes, assignments, and past exams are separated correctly.
- Add past exams when available. The weighted retriever gives them more influence for exam-oriented tasks.
- Use `Quick Review` when you want faster, cheaper output.
- Use `Deep Analysis` when quality matters more than latency or token cost.
- Use local embeddings if you want to reduce cloud costs.
- Reuse the same session for the same course so the app can reuse the saved index and chat history.

### CLI: Step-by-step

The CLI is an interactive terminal assistant, not a one-shot generator.

1. Install the package with `pip install -e .`.
2. Set your provider key(s) in `<app_data_dir>/.env`, `cwd/.env`, or your shell
   environment. The CLI checks `<app_data_dir>/.env` first.
3. Start the CLI with one or more course files and a course name.
   Supported inputs include PDF, DOCX, CSV, and common text/code formats.
4. Wait for startup indexing to finish.
5. Ask questions or request generated study documents in natural language.
6. Exit with `exit`, `quit`, `Ctrl-C`, or `Ctrl-D`.

CLI working files are stored under `<app_data_dir>/cli_run/<workspace_id>/`.
Inside that workspace, the app keeps its own bundle under
`<workspace>/.uacragent/`.

Example:

```bash
python -m uacragent outline.pdf lecture1.pdf lecture2.pdf \
  --course-name "Introduction to Algorithms" \
  --doc-type lecture_note \
  --exam-type final \
  --exam-format written \
  --effort-level medium \
  --workspace-id algo-final
```

CLI behavior to remember:

- All positional files are treated as the same `--doc-type` when you provide one.
- If you omit `--doc-type`, all input files are treated as `other`.
- The CLI reuses the same workspace when you reuse `--workspace-id`.
- The CLI currently exposes `effort_level` only, not the desktop reasoning-mode toggle.

### API: Step-by-step

The FastAPI layer is the programmatic one-shot generation interface.

1. Start the server with `uvicorn uacragent.api.main:app --reload`.
   The API currently reads `.env` from the server's current working directory.
2. Prepare a JSON body with:
   - `classified_files`
   - `course_name`
   - optional exam/course metadata
   - `task_type`
   - optional `effort_level`
   - optional `reasoning_mode`
   - absolute file paths for every source document
3. Send a `POST /review` request.
4. Read the returned plan plus the saved markdown path.

API working files are stored under `<app_data_dir>/api_run/<workspace_id>/`.
Inside that workspace, the app keeps its own bundle under
`<workspace>/.uacragent/`.

Use the API when you want to integrate generation into another app, script, or service. Use the desktop GUI when you want persistent sessions, interactive study chat, and richer controls.

### Desktop Session Persistence

The desktop app persists session state so you can return to previous work.

- Bootstrap config: `~/.uacragent/config.json`
- Default app data directory: `~/.uacragent/`
- Session index: `<app_data_dir>/index.json`
- Local embedding model cache: `<app_data_dir>/models/`
- Auto-created GUI workspaces: `<app_data_dir>/sessions/<workspace_id>/`
- CLI workspaces: `<app_data_dir>/cli_run/<workspace_id>/`
- API workspaces: `<app_data_dir>/api_run/<workspace_id>/`
- Per-session agent bundle: `<workspace>/.uacragent/`
- Per-session state file: `<workspace>/.uacragent/session.json`

Persisted session data includes course settings, selected files, chosen
provider/model, chat history, and session UI extras such as export format and
embedding selection. App-level appearance preferences (color mode, font size,
language) are stored separately in the bootstrap config. API keys are not
saved.

Notes:

- New sessions get a unique autogenerated `workspace_id`, so auto-created
  workspaces do not collide with each other.
- The app data directory can be changed from the session-list pane’s global
  app settings button and takes full effect after restarting the app.
- Global appearance settings are persisted in the bootstrap config and include
  light/dark mode, small/medium/large font size, and `Auto` / `en` / `zh_CN` UI language.
- Local embedding models are cached under `<app_data_dir>/models/`, including
  the frozen app’s ONNX backend under
  `<app_data_dir>/models/chroma/onnx_models/`.
- Desktop and API logs are written under
  `<app_data_dir>/logs/uacragent.log`. The default log level is `WARNING` —
  only warnings, errors, and security events are captured; routine operations
  are silent. Set `UACRAGENT_LOG_LEVEL=DEBUG` before launch for verbose output.
  Verbose third-party libraries (LangChain, ChromaDB, httpx, etc.) are always
  clamped to `WARNING` even in DEBUG mode. API keys and message content are
  never written to the log.
- All agent-generated files inside a workspace are grouped under
  `<workspace>/.uacragent/` so they stay separate from the user’s own files.
- Once a session has been created and its workspace committed, that workspace
  is treated as fixed for the lifetime of the session.
- Deleting a session removes the `<workspace>/.uacragent/` bundle. Original
  source files outside that folder are not affected. For auto-created workspaces
  (those under `<app_data_dir>/sessions/`), the workspace folder itself is also
  removed when it contains no other files after the bundle is deleted.

### Changing the App Data Folder

The app data folder can be changed in App Settings. Before doing so, read the
following carefully:

**Sessions are not migrated.** Changing the folder does not move any existing
data. Sessions created under the old folder remain there and will not appear in
the session list until you switch back. If you want to continue using existing
sessions, switch back to the original folder in App Settings.

**Do not point the app at a folder that already contains unrelated files.** The
app writes its own files (index.json, session workspaces, model cache, logs)
directly into the chosen folder. Using a folder that already contains your own
documents or other application data risks name collisions and makes the app’s
files harder to identify and manage.

Recommended practice:

- Use a dedicated, initially empty folder as the app data directory.
- If you need to relocate your data, manually copy the entire old app data
  folder to the new location first, then point the app at the new path.
- If you change the folder by mistake, switch back immediately in App Settings
  — the original folder and its sessions are still intact.

## Run (CLI)

`--course-name` is **required** for CLI runs with input files.

The CLI examples below assume you completed `pip install -e .` during setup.
The CLI uses the provider configured through `LLM_PROVIDER`/`LLM_MODEL` and the
matching API key from your environment.

`--workspace-id` controls the workspace folder name under
`<app_data_dir>/cli_run/`. Reusing the same ID lets the CLI reuse the same
persisted Chroma store and outputs for unchanged files, which can avoid
re-embedding work and additional embedding API calls on later runs.

CLI runs also respect `EMBEDDING_PROVIDER`. For example, you can use DeepSeek
for chat/generation together with `EMBEDDING_PROVIDER=local` to avoid cloud
embedding costs.

The CLI also supports `--effort-level low|medium|high` to control retrieval
depth for each chat turn and generated document request.

The current CLI does not expose the desktop-only `Quick Review` / `Deep
Analysis` reasoning-mode toggle. Generated documents from the CLI use the
default quick reasoning pipeline.

How the current CLI works:

- It indexes the supplied files at startup, or reuses the existing workspace index when the file set is unchanged.
- It shows live progress updates while indexing documents and generating study documents.
- It then enters an interactive chat loop in the terminal.
- You can ask course questions or request a generated document in natural language.
- Generated outputs are saved to the workspace and their paths are printed in the terminal.

Start an interactive CLI session with course files:
```bash
python -m uacragent outline.pdf lecture.pdf \
  --course-name "Introduction to Algorithms" \
  --exam-format written \
  --effort-level medium
```

Use explicit document typing for all supplied files:
```bash
python -m uacragent syllabus.pdf \
  --course-name "Data Structures" \
  --doc-type syllabus \
  --exam-type final \
  --exam-format mixed \
  --university-name "University of Toronto" \
  --major "Computer Science" \
  --course-code "CSC263" \
  --professor-name "Dr. Smith" \
  --semester "Fall 2024" \
  --exam-duration "2 hours" \
  --workspace-id csc263-final
```

Once the CLI starts, you can type requests such as:

- `Explain the main topics covered in these notes.`
- `Generate a review summary for this course.`
- `Generate a practice booklet for this course.`
- `Generate a mock exam for this course.`
- `Generate an exam prediction for this course.`

To leave the terminal chat, type `exit` or press `Ctrl-C` / `Ctrl-D`.

### app.py

[app.py](app.py) is no longer the main interactive entrypoint. It is a small
repo-level helper that exposes `main()` / `main_simple()` for direct import and
prints guidance to use `python -m uacragent` if run as a script.

## Run (API)

Start the server:

- `uvicorn uacragent.api.main:app --reload`

The API also uses the provider configured through `LLM_PROVIDER`/`LLM_MODEL`
and the matching API key from the environment.

`workspace_id` in API requests resolves to a folder under
`<app_data_dir>/api_run/`.

The API likewise respects `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, and
`LOCAL_EMBEDDING_MODEL` in source installs. Frozen app builds use the ONNX
local embedding path instead:

- `all-MiniLM-L6-v2` under `<app_data_dir>/models/chroma/onnx_models/`

`copy_to_workspace` controls whether uploaded source files are copied into the
workspace's `.uacragent/uploads/` bundle during API generation. Leave it at
`true` for the normal self-contained workspace behavior.

`markdown_path` in the API response is the absolute local path to the saved
Markdown file on the same machine that is running the API server. In the
current local-only design, this is intended for trusted local callers that can
open the returned file directly.

Security note:

- Without `UACRAGENT_ALLOWED_BASE_DIR`, the API accepts any absolute existing
  file path on the host machine.
- The current API is intended for local trusted use, not public or multi-user
  deployment.
- If you want an extra local safety boundary, set
  `UACRAGENT_ALLOWED_BASE_DIR` to restrict file access to a trusted directory
  tree.

API file-path rules:

- every file path in `classified_files` must be absolute
- the path must point to an existing regular file
- if `UACRAGENT_ALLOWED_BASE_DIR` is set, the file must resolve under that directory

The API exposes both depth controls:

- `effort_level` controls retrieval/context depth
- `reasoning_mode` controls generation pipeline depth (`quick` or `deep`)

Endpoints:

- `GET /health` — health check
- `POST /review` — generate output with classified documents:
  ```json
  {
    "classified_files": {
      "syllabus": ["path/to/syllabus.pdf"],
      "lecture_note": ["path/to/notes.pdf"],
      "past_exam": ["path/to/exam1.pdf"]
    },
    "course_name": "Introduction to Algorithms",
    "exam_format": "written",
    "exam_type": "final",
    "task_type": "review_summary",
    "extra_instructions": "",
    "effort_level": "medium",
    "reasoning_mode": "quick",
    "workspace_id": "default",
    "copy_to_workspace": true,
    "university_name": "University of Toronto",
    "major": "Computer Science",
    "course_code": "CSC263",
    "professor_name": "Dr. Smith",
    "semester": "Fall 2024",
    "exam_duration": "2 hours",
    "exam_info": "Closed book. One formula sheet allowed."
  }
  ```

`course_name` is required in the review request. `effort_level` is optional and
accepts `low`, `medium`, or `high`. `reasoning_mode` is optional and accepts
`quick` or `deep`. All other fields (`university_name`, `major`,
`course_code`, `professor_name`, `semester`, `exam_duration`, `exam_info`) are
optional.

## Output

- Canonical output is written to `<workspace>/.uacragent/outputs/review_<timestamp>.md`
- API responses return that saved Markdown location as an absolute local
  `markdown_path`
- When using the desktop GUI, optional DOCX/PDF exports are written to the same output folder
- Uploaded file copies are organized under `<workspace>/.uacragent/uploads/<doc_type>/`
- Vector DB is persisted under `<workspace>/.uacragent/chroma_db/`
- The generated document header includes all provided course information fields

Workspace resolution:

- Desktop GUI with a custom workspace folder: `<workspace>` is the chosen folder
- Desktop GUI with auto workspace: `<workspace>` is `<app_data_dir>/sessions/<workspace_id>/`
- CLI: `<workspace>` is `<app_data_dir>/cli_run/<workspace_id>/`
- API: `<workspace>` is `<app_data_dir>/api_run/<workspace_id>/`

## Project structure

```
src/uacragent/
  __main__.py            Interactive CLI + desktop GUI entry point
  agent/
    service.py           High-level orchestrator (AgentService)
    conversation.py      Conversational agent for session-based chat + task triggering
    session.py           Session state container for chat, files, and preferences
    pipeline.py          RAG pipeline with task-type dispatch
    reasoning.py         Reasoning-mode configuration, topic extraction, and critic/refinement passes
    workspace_manager.py Workspace cleanup helpers for Apply / re-index flows
    prompts/
      _prompts.py                    Shared prompt-directory path + language-steering helpers
      conversation_system.md         System prompt for desktop chat sessions
      review_summary_planner.md      Review summary planner
      review_summary_writer.md       Review summary writer
      practice_booklet_planner.md    Practice booklet planner
      practice_booklet_writer.md     Practice booklet writer
      mock_exam_planner.md           Mock exam planner
      mock_exam_writer.md            Mock exam writer
      exam_prediction_planner.md     Exam prediction planner
      exam_prediction_writer.md      Exam prediction analysis writer (Part A)
      exam_prediction_paper_writer.md Predicted exam paper writer (Part B)
      topic_extraction.md            Deep-analysis topic extraction prompt
      section_critic.md              Deep-analysis refinement / critic prompt
  api/
    main.py              FastAPI application factory
    routes.py            API endpoints (/health, /review)
    schemas.py           Request / response models (enum-validated fields)
    deps.py              Dependency injection (settings, service singletons)
  domain/
    models.py            Core data models (ReviewPlan, SectionSpec)
    errors.py            Custom exception hierarchy
    providers.py         Provider metadata, labels, and env-var mapping
    doc_priorities.py    Task-aware document weighting presets for retrieval
    rate_tiers.py        API plan tier presets for request pacing
    types.py             Enums (DocumentType, ExamFormat, ExamType, TaskType, ExportFormat)
  infra/
    settings.py          Pydantic-based configuration (.env)
    loaders.py           Document loading with multi-stage type-specific splitting, including CSV table ingestion
    vectorstore.py       Chroma vector store, manifest tracking, and weighted retriever
    llm.py               Provider-aware LLM client wrapper (Gemini / OpenAI / DeepSeek)
    auth.py              Provider-specific API key validation
    persistence.py       Desktop session persistence, app-data config, and local model cache management
    workspace.py         Workspace directory management with classified folders
  export/
    markdown.py          Markdown export
    docx.py              DOCX export (python-docx)
    pdf.py               PDF export (fpdf2, Unicode font auto-detection)
  ui/
    desktop/
      app.py             Tkinter desktop entrypoint that composes the GUI mixins
      _custom_widgets.py Shared custom widgets for rounded chips, session list, and sidebar controls
      _ui_constants.py   Shared UI strings, themes, OS helpers, and i18n tables
      _appearance_mixin.py Theme, font-size, language, and App Settings logic
      _settings_mixin.py Session Settings dialog and validation flow
      _session_mixin.py  Session list management and persistence hooks
      _chat_mixin.py     Chat send/receive flow, indexing, and output-link UI
  assets/
    UACRAgent.icns      macOS app-bundle icon asset
    logo_icns_source.png Source PNG used to generate the macOS ICNS asset
    logo_*.png/svg/ico  Desktop and package icon variants
tests/
  test_domain.py         Domain model and enum tests
  test_export.py         Markdown / DOCX / PDF export tests
  test_loaders.py        Document loading and splitting tests
  test_pipeline_utils.py Pipeline utility function tests
  test_workspace.py      Workspace path and directory tests
app.py                   Lightweight importable helper for direct service calls
.env.sample              Example environment configuration
UACRAgent_mac.spec       PyInstaller spec for macOS standalone builds
UACRAgent_win.spec       PyInstaller spec for Windows standalone builds
LICENSE                  MIT license text
```

## Credits

Thanks to the volunteer test users who helped exercise the desktop assistant,
retrieval flow, workspace handling, and study-support UX during development.
Their feedback helped make this agent better.

- Test-user credits will be listed here once they are confirmed for public acknowledgement.
