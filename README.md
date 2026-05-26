# University Academic Course Review Agent (UACRAgent)

Study from course documents with a grounded academic assistant, and generate
review materials when you need them through a persistent desktop chat workflow.

- Ingest course materials (PDF, TXT, Markdown, or DOCX)
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

## Embedding Providers

Document retrieval embeddings are configured independently from the chat/writer
LLM provider:

| Provider | Use Cases                                  | Requirements                            |
|----------|--------------------------------------------|-----------------------------------------|
| Gemini   | Cloud embeddings                           | `GOOGLE_API_KEY`                        |
| OpenAI   | Cloud embeddings                           | `OPENAI_API_KEY`                        |
| Local    | On-device sentence-transformers embeddings | No API key; first use downloads a model |

The desktop GUI exposes all three embedding options. Local embeddings are free
to run after the model has been downloaded and cached.

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
- The desktop GUI accepts an exam info sheet as a file attachment.
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
  - local sentence-transformers embeddings with no API key

Notes:

- Running the pipeline will make paid model requests (LLM + embeddings).
- DeepSeek can be used for chat/planning/writing together with either cloud
  embeddings or local embeddings.
- Local embeddings download a HuggingFace model on first use, then run from the
  local cache afterward.

## Install

1) Create and activate a virtual environment

- `python3 -m venv .venv`
- macOS/Linux: `source .venv/bin/activate`
- Windows: `.venv\Scripts\activate`

2) Install dependencies and the package

- `pip install -r requirements.txt`
- `pip install -e .`

The editable install is recommended because this repository uses a `src/`
layout. Without it, `python -m uacragent` will not resolve unless you
manually set `PYTHONPATH=src`.

## Configure

### API Keys

Create a `.env` file in the repo root (copy from `.env.sample`) and set the
provider key(s) you want to use:

```env
GOOGLE_API_KEY=your-google-api-key-here
# OPENAI_API_KEY=your-openai-api-key-here
# DEEPSEEK_API_KEY=your-deepseek-api-key-here
```

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
- `EMBEDDING_PROVIDER=local` uses a local sentence-transformers model with no API key

For local embeddings, you can choose the downloaded model with
`LOCAL_EMBEDDING_MODEL`.

> Security note: API key fields are excluded from `Settings` repr output, and
> the desktop session persistence layer intentionally does not write API keys to disk.

### Other settings

Optional overrides (see defaults in [src/uacragent/infra/settings.py](src/uacragent/infra/settings.py)):

```
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.5-flash
EMBEDDING_PROVIDER=gemini
EMBEDDING_MODEL=gemini-embedding-001
LOCAL_EMBEDDING_MODEL=all-MiniLM-L6-v2
RETRIEVER_K=8
RATE_TIER=free
```

#### Request Frequency / Rate Limiting

Sections are written **sequentially** (one at a time) to avoid overwhelming the
API. The app now uses a named `RATE_TIER` by default, which maps to concrete
delay/retry settings:

| Tier        | Delay | Retries | Base Retry Delay | Typical Use |
|-------------|-------|---------|------------------|-------------|
| `free`      | `6.0` | `3`     | `15.0`           | Free and trial plans |
| `standard`  | `1.5` | `2`     | `8.0`            | Entry paid plans |
| `pro`       | `0.3` | `2`     | `4.0`            | Higher paid tiers |
| `unlimited` | `0.0` | `1`     | `2.0`            | Very high-capacity plans |

If you prefer raw numeric overrides, clear `RATE_TIER` and then set
`LLM_REQUEST_DELAY`, `LLM_MAX_RETRIES`, and `LLM_RETRY_BASE_DELAY` directly.

Current raw-setting defaults:

| Variable               | Default | Description                                                                                      |
|------------------------|---------|--------------------------------------------------------------------------------------------------|
| `LLM_REQUEST_DELAY`    | `6.0`   | Seconds to wait after each LLM call completes before starting the next                           |
| `LLM_MAX_RETRIES`      | `3`     | Max retry attempts on transient 503/429/quota errors (keep low — retries generate more requests) |
| `LLM_RETRY_BASE_DELAY` | `15.0`  | Initial backoff delay in seconds before the first retry (doubles each attempt, capped at 60 s)   |

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
- Pick a free local embedding model when using on-device embeddings
- Enter a **course name** and optional course details
- Add files to different document type categories (Syllabus, Lecture Notes, etc.)
- Search and filter saved sessions from the sidebar search bar
- Choose exam settings and export format
- Choose per-message effort level (`low`, `medium`, `high`) for chat and generated outputs
- Pick a custom workspace folder before the first **Apply**, or let the app auto-create one
- Use **Apply** to commit setting changes and re-index with the updated session configuration
- Chat with the assistant about the course material
- Toggle provider-backed web search for the next message when supported by the active provider
- Attach supported files to chat messages, including drag-and-drop onto the chat area when desktop drag-and-drop support is available
- Use quick actions to generate a Review Summary, Practice Booklet, Mock Exam, or Exam Prediction
- Open generated outputs directly from the chat transcript
- Cancel an in-flight indexing or chat request from the main panel
- Open global app settings to change color mode, font size, language (`en` / `zh_CN`), and the shared app data directory
- Use the selected desktop language to steer assistant replies and generated document headings in English or Simplified Chinese

Works on macOS, Windows, and Linux.

Desktop note:
- File drag-and-drop in the chat area uses `tkinterdnd2` when the Tk extension
  is available. The desktop app still works without it; only drag-and-drop is
  disabled in that case.

When you reopen an existing desktop session from the sidebar, the app first
tries a fast attach path. If the saved Chroma index and indexed-file manifest
still match the current file set, it reuses the existing retriever without
re-embedding or making new embedding API calls. A full re-index runs when the
files changed, the index is missing, or you click **Apply** to force current
settings to take effect. On this fast path the session becomes ready silently,
without adding a new "documents indexed" notice to the chat transcript.

### Desktop Session Persistence

The desktop app persists session state so you can return to previous work.

- Bootstrap config: `~/.uacragent/config.json`
- Default app data directory: `~/.uacragent/`
- Session index: `<app_data_dir>/index.json`
- Local embedding model cache: `<app_data_dir>/models/`
- Auto-created workspaces: `<app_data_dir>/sessions/<workspace_id>/`
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
  light/dark mode, small/medium/large font size, and `en` / `zh_CN` UI language.
- Local embedding models are cached under `<app_data_dir>/models/` via
  HuggingFace cache redirection.
- All agent-generated files inside a workspace are grouped under
  `<workspace>/.uacragent/` so they stay separate from the user’s own files.
- Once a session has been created and its workspace committed, that workspace
  is treated as fixed for the lifetime of the session.
- Deleting a session removes the `<workspace>/.uacragent/` bundle. Original
  source files outside that folder are not affected.

## Run (CLI)

`--course-name` is **required** for CLI runs with input files.

The CLI examples below assume you completed `pip install -e .` during setup.
The CLI uses the provider configured through `LLM_PROVIDER`/`LLM_MODEL` and the
matching API key from your environment.

`--workspace-id` controls the workspace folder name under the app data
directory. Reusing the same ID lets the CLI reuse the same persisted Chroma
store and outputs for unchanged files, which can avoid re-embedding work and
additional embedding API calls on later runs.

CLI runs also respect `EMBEDDING_PROVIDER`. For example, you can use DeepSeek
for chat/generation together with `EMBEDDING_PROVIDER=local` to avoid cloud
embedding costs.

The CLI also supports `--effort-level low|medium|high` to control retrieval
depth for each chat turn and generated document request.

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

`workspace_id` in API requests resolves to a folder under the app data
directory in the same way as the CLI.

The API likewise respects `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, and
`LOCAL_EMBEDDING_MODEL`.

`copy_to_workspace` controls whether uploaded source files are copied into the
workspace's `.uacragent/uploads/` bundle during API generation. Leave it at
`true` for the normal self-contained workspace behavior.

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
accepts `low`, `medium`, or `high`. All other fields (`university_name`,
`major`, `course_code`, `professor_name`, `semester`, `exam_duration`,
`exam_info`) are optional.

## Output

- Canonical output is written to `<workspace>/.uacragent/outputs/review_<timestamp>.md`
- When using the desktop GUI, optional DOCX/PDF exports are written to the same output folder
- Uploaded file copies are organized under `<workspace>/.uacragent/uploads/<doc_type>/`
- Vector DB is persisted under `<workspace>/.uacragent/chroma_db/`
- The generated document header includes all provided course information fields

Workspace resolution:

- Desktop GUI with a custom workspace folder: `<workspace>` is the chosen folder
- Desktop GUI with auto workspace: `<workspace>` is `<app_data_dir>/sessions/<workspace_id>/`
- CLI / API: `<workspace>` is `<app_data_dir>/<workspace_id>/`

## Project structure

```
src/uacragent/
  __main__.py            Interactive CLI + desktop GUI entry point
  agent/
    service.py           High-level orchestrator (AgentService)
    conversation.py      Conversational agent for session-based chat + task triggering
    session.py           Session state container for chat, files, and preferences
    pipeline.py          RAG pipeline with task-type dispatch
    prompts/
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
    loaders.py           Document loading with multi-stage type-specific splitting
    vectorstore.py       Chroma vector store, manifest tracking, and weighted retriever
    llm.py               Provider-aware LLM client wrapper (Gemini / OpenAI / DeepSeek)
    auth.py              Provider-specific API key validation
    persistence.py       Desktop session persistence, app-data config, and HF cache management
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
tests/
  test_domain.py         Domain model and enum tests
  test_export.py         Markdown / DOCX / PDF export tests
  test_loaders.py        Document loading and splitting tests
  test_pipeline_utils.py Pipeline utility function tests
  test_workspace.py      Workspace path and directory tests
app.py                   Lightweight importable helper for direct service calls
.env.sample              Example environment configuration
LICENSE                  MIT license text
```

## Credits

Thanks to the volunteer test users who helped exercise the desktop assistant,
retrieval flow, workspace handling, and study-support UX during development.
Their feedback helped make this agent better.

- Test-user credits can be listed here once they are confirmed for public acknowledgement.
