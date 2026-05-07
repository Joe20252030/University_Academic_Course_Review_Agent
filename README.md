# University Academic Course Review Agent (UACRAgent)

Generate exam review materials from course documents using a RAG pipeline, and
interact with those materials through a persistent desktop chat assistant.

- Ingest course materials (PDF, TXT, Markdown, or DOCX)
- Classify documents by type for optimized processing
- Chunk documents using type-specific multi-stage splitting strategies
- Embed into a local Chroma vector store
- Ask an LLM to answer questions in a session-aware chat workflow
- Ask an LLM to create a structured plan tailored to the chosen study-document task
- For each planned section, retrieve relevant content and generate material sequentially
- Save the canonical output as Markdown, with optional DOCX/PDF export in the desktop GUI
- Persist desktop sessions, settings, and chat history across app restarts

## License

This project is released under the **MIT License**. See [LICENSE](LICENSE).

## Interfaces

The project currently has three user-facing interfaces:

- **Desktop GUI**: the primary interface, now built as a persistent conversational assistant with session management
- **CLI**: direct one-shot document generation
- **FastAPI API**: programmatic one-shot document generation

## Task Types

The agent supports four distinct output modes:

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

| Provider | Use Cases | Required Key |
|----------|-----------|--------------|
| Gemini   | Chat, planning, writing, embeddings | `GOOGLE_API_KEY` |
| OpenAI   | Chat, planning, writing, embeddings | `OPENAI_API_KEY` |
| DeepSeek | Chat, planning, writing | `DEEPSEEK_API_KEY` |

Embeddings currently come from Gemini when available, otherwise OpenAI.

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
| Course Department  | No       | `Computer Science`                                              |
| Course Code        | No       | `CSC263`                                                        |
| Professor          | No       | `Dr. Jane Smith`                                                |
| Semester           | No       | `Fall 2024`                                                     |
| Exam Duration      | No       | `2 hours` or `90 minutes`                                       |
| Exam Info Sheet    | No       | `Closed book. One formula sheet allowed. Topics: chapters 1-6.` |

All fields are passed to every planner and writer prompt, so the LLM can tailor content to the specific course and context. The **Exam Duration** and **Exam Info Sheet** fields are especially useful for generating realistic mock exams and practice booklets that match the actual exam constraints.

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
- An embedding-capable API key for retrieval:
  - Google Gemini embeddings are used when `GOOGLE_API_KEY` is available
  - otherwise OpenAI embeddings are used when `OPENAI_API_KEY` is available

Notes:

- Running the pipeline will make paid model requests (LLM + embeddings).
- DeepSeek can be used for chat/planning/writing, but embeddings still require
  either Gemini or OpenAI credentials.

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

Embedding behavior:

- Gemini embeddings are used when `GOOGLE_API_KEY` is available
- otherwise OpenAI embeddings are used when `OPENAI_API_KEY` is available

That means a DeepSeek-only setup is not enough for retrieval; you still need
either Gemini or OpenAI credentials for embeddings.

> Security note: API key fields are excluded from `Settings` repr output, and
> the desktop session persistence layer intentionally does not write API keys to disk.

### Other settings

Optional overrides (see defaults in [src/uacragent/infra/settings.py](src/uacragent/infra/settings.py)):

```
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.5-flash
EMBEDDING_MODEL=gemini-embedding-001
RETRIEVER_K=8
```

#### Rate limiting

Sections are written **sequentially** (one at a time) to avoid overwhelming the API. A configurable pause is inserted between each call.

If you still see `503 ServiceUnavailable` or `429 Too Many Requests` errors, increase `LLM_REQUEST_DELAY`:

| Variable | Default | Description |
|---|---|---|
| `LLM_REQUEST_DELAY` | `3.0` | Seconds to wait after each LLM call completes before starting the next |
| `LLM_MAX_RETRIES` | `2` | Max retry attempts on transient 503/429/quota errors (keep low — retries generate more requests) |
| `LLM_RETRY_BASE_DELAY` | `10.0` | Initial backoff delay in seconds before the first retry (doubles each attempt, capped at 60 s) |

## Run (Desktop GUI)

- `python -m uacragent --gui`
- `python -m uacragent` (launches the GUI when no file arguments are given)
- `python -m uacragent.ui.desktop.app`

The GUI lets you:
- Create, rename, delete, and reopen persistent study sessions
- Choose an LLM provider (`gemini`, `openai`, or `deepseek`) and model per session
- Enter provider API keys in the settings dialog when they are not already set in `.env`
- Enter a **course name** and optional course details
- Add files to different document type categories (Syllabus, Lecture Notes, etc.)
- Choose exam settings and export format
- Pick a custom workspace folder before first load, or let the app auto-create one
- Click **Load Session** to commit the workspace path and index documents into the session retriever
- Chat with the assistant about the course material
- Use quick actions to generate a Review Summary, Practice Booklet, Mock Exam, or Exam Prediction
- Open generated outputs directly from the chat transcript

Works on macOS, Windows, and Linux.

### Desktop Session Persistence

The desktop app persists session state so you can return to previous work.

- Bootstrap config: `~/.uacragent/config.json`
- Default app data directory: `~/.uacragent/`
- Session index: `<app_data_dir>/index.json`
- Auto-created workspaces: `<app_data_dir>/<workspace_id>/`
- Per-session state file: `<workspace>/session.json`

Persisted data includes course settings, selected files, chosen provider/model,
chat history, and UI extras such as export format. API keys are not saved.

Notes:

- New sessions get a unique autogenerated `workspace_id`, so auto-created
  workspaces do not collide with each other.
- The app data directory can be changed from the session-list pane’s global
  app settings button and takes full effect after restarting the app.
- Once a session has been loaded and its workspace committed, that workspace is
  treated as fixed for the lifetime of the session.
- Deleting a session removes agent-created artifacts inside its workspace,
  including `session.json`, `uploads/`, `outputs/`, and `chroma_db/`. Original
  source files outside the workspace are not affected.

## Run (CLI)

`--course-name` is **required** for all CLI runs.

The CLI examples below assume you completed `pip install -e .` during setup.
The CLI uses the provider configured through `LLM_PROVIDER`/`LLM_MODEL` and the
matching API key from your environment.

`--workspace-id` controls the output folder name under the app data directory.
By default, one-shot CLI runs write to `~/.uacragent/default/` unless the app
data directory has been changed by the desktop app.

Simple review summary (all files treated as "other"):
```
python -m uacragent outline.pdf lecture.pdf \
  --course-name "Introduction to Algorithms" \
  --exam-format written
```

With all options:
```
python -m uacragent syllabus.pdf \
  --course-name "Data Structures" \
  --doc-type syllabus \
  --exam-type final \
  --task-type mock_exam \
  --exam-format mixed \
  --university-name "University of Toronto" \
  --major "Computer Science" \
  --course-code "CSC263" \
  --professor-name "Dr. Smith" \
  --semester "Fall 2024" \
  --exam-duration "2 hours" \
  --exam-info "Closed book. One double-sided formula sheet allowed. Topics: chapters 1-6."
```

Generate a practice booklet for a midterm:
```
python -m uacragent notes.pdf \
  --course-name "Linear Algebra" \
  --task-type practice_booklet \
  --exam-type midterm \
  --exam-format written
```

With extra instructions:
```
python -m uacragent notes.pdf \
  --course-name "Graph Theory" \
  --task-type exam_prediction \
  --extra-instructions "Professor emphasized graph theory"
```

Quick-start script:
- `python app.py`

By default, [app.py](app.py) runs against the included PDF fixture under `test_materials/outlines/`.

## Run (API)

Start the server:

- `PYTHONPATH=src uvicorn uacragent.api.main:app --reload`

The API also uses the provider configured through `LLM_PROVIDER`/`LLM_MODEL`
and the matching API key from the environment.

`workspace_id` in API requests resolves to a folder under the app data
directory in the same way as the CLI.

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
- `POST /review/simple` — legacy endpoint (all files treated as "other"):
  ```json
  {
    "file_paths": ["path/to/file.pdf"],
    "course_name": "Introduction to Algorithms",
    "exam_format": "written",
    "exam_type": "other",
    "task_type": "review_summary",
    "workspace_id": "default",
    "exam_duration": "90 minutes",
    "exam_info": "Open book. Topics: chapters 1-4."
  }
  ```

`course_name` is required in both endpoints. All other fields (`university_name`, `major`, `course_code`, `professor_name`, `semester`, `exam_duration`, `exam_info`) are optional.

## Output

- Canonical output is written to `<workspace>/outputs/review_<timestamp>.md`
- When using the desktop GUI, optional DOCX/PDF exports are written to the same output folder
- Uploaded files are organized under `<workspace>/uploads/<doc_type>/`
- Vector DB is persisted under `<workspace>/chroma_db/`
- The generated document header includes all provided course information fields

Workspace resolution:

- Desktop GUI with a custom workspace folder: `<workspace>` is the chosen folder
- Desktop GUI with auto workspace: `<workspace>` is `<app_data_dir>/<workspace_id>/`
- CLI / API: `<workspace>` is `<app_data_dir>/<workspace_id>/`

## Project structure

```
src/uacragent/
  __main__.py            CLI + GUI entry point
  agent/
    service.py           High-level orchestrator (AgentService)
    conversation.py      Conversational agent for session-based chat + task triggering
    session.py           Session state container for chat, files, and preferences
    pipeline.py          RAG pipeline with task-type dispatch
    prompts/
      conversation_system.md       System prompt for desktop chat sessions
      planner.md                   Generic planner (fallback)
      reviewer.md                  Generic writer (fallback)
      review_summary_planner.md    Review summary planner
      review_summary_writer.md     Review summary writer
      practice_booklet_planner.md  Practice booklet planner
      practice_booklet_writer.md   Practice booklet writer
      mock_exam_planner.md         Mock exam planner
      mock_exam_writer.md          Mock exam writer
      exam_prediction_planner.md   Exam prediction planner
      exam_prediction_writer.md    Exam prediction writer
      exam_prediction_paper_writer.md Predicted exam paper writer (Part B)
  api/
    main.py              FastAPI application factory
    routes.py            API endpoints (/health, /review, /review/simple)
    schemas.py           Request / response models (enum-validated fields)
    deps.py              Dependency injection (settings, service singletons)
  domain/
    models.py            Core data models (ReviewPlan, SectionSpec)
    errors.py            Custom exception hierarchy
    types.py             Enums (DocumentType, ExamFormat, ExamType, TaskType, ExportFormat)
  infra/
    settings.py          Pydantic-based configuration (.env)
    loaders.py           Document loading with multi-stage type-specific splitting
    vectorstore.py       Chroma vector store with dedup
    llm.py               Provider-aware LLM client wrapper (Gemini / OpenAI / DeepSeek)
    auth.py              Provider-specific API key validation
    persistence.py       Desktop session persistence and index management
    workspace.py         Workspace directory management with classified folders
  export/
    markdown.py          Markdown export
    docx.py              DOCX export (python-docx)
    pdf.py               PDF export (fpdf2, Unicode font auto-detection)
  ui/
    desktop/
      app.py             Tkinter conversational desktop GUI with session manager
tests/
  test_domain.py         Domain model and enum tests
  test_export.py         Markdown / DOCX / PDF export tests
  test_loaders.py        Document loading and splitting tests
  test_pipeline_utils.py Pipeline utility function tests
  test_workspace.py      Workspace path and directory tests
app.py                   Script entry point (quick-start)
.env.sample              Example environment configuration
LICENSE                  MIT license text
```
