# University Academic Course Review Agent (UACRAgent)

Generate a comprehensive final-exam review document from course materials using a RAG pipeline:

- Ingest course materials (PDF, TXT, Markdown, or DOCX)
- Classify documents by type for optimized processing
- Chunk documents using type-specific strategies
- Embed into a local Chroma vector store
- Ask an LLM to create a structured review plan
- For each planned section, retrieve relevant content and generate review material
- Export to Markdown, DOCX, or PDF

## Document Types & Splitting Strategies

Each document type uses a multi-stage splitting pipeline optimized for its structure:

| Type | Splitting Strategy | Final Chunk Size |
|------|-------------------|-----------------|
| **Textbook** | Markdown header split (chapter/section/subsection) then recursive character split | 1500 |
| **Syllabus** | Markdown header split (section/subsection) then recursive character split | 800 |
| **Lecture Notes** | Sentence-aware recursive split (preserves slide bullet points) | 1000 |
| **Past Exam** | Question-boundary regex split (Q1, 1., Part A, (a), etc.) then recursive split | 500 |
| **Assignment** | Problem-boundary regex split (Problem/Exercise/Task headers) then recursive split | 600 |
| **Other** | Standard recursive character split | 1000 |

Multi-stage pipelines feed each stage's output into the next. For example, a textbook
PDF is first split on `#`/`##`/`###` markdown headers to isolate chapters and sections,
then each section is recursively split into retrieval-sized chunks. Header-based
metadata (chapter, section, subsection) is preserved on every chunk.

## Requirements

- Python 3.10+
- A Google Gemini API key (used for planning, writing, and embeddings)

Note: running the pipeline will make paid model requests (LLM + embeddings).

## Install

1) Create and activate a virtual environment

- `python -m venv .venv`
- macOS/Linux: `source .venv/bin/activate`
- Windows: `.venv\Scripts\activate`

2) Install dependencies

- `pip install -r requirements.txt`

## Configure

Create a `.env` file in the repo root:

- `GOOGLE_API_KEY=<your-key>`

Optional overrides (see defaults in [src/uacragent/infra/settings.py](src/uacragent/infra/settings.py)):

- `LLM_MODEL=gemini-2.5-flash`
- `EMBEDDING_MODEL=gemini-embedding-001`
- `RETRIEVER_K=8`
- `WORKSPACE_ROOT=data`

## Run (Desktop GUI)

- `python -m uacragent --gui`
- `python -m uacragent` (launches the GUI when no file arguments are given)
- `python -m uacragent.ui.desktop.app`

The GUI lets you:
- Add files to different document type categories (Syllabus, Lecture Notes, etc.)
- Choose exam format (written / mcq / mixed)
- Choose export format (Markdown / DOCX / PDF)
- Generate a review with one click

Works on macOS, Windows, and Linux.

## Run (CLI)

Simple mode (all files treated as "other"):
- `python -m uacragent outline.pdf lecture.pdf --exam-format written`

With document type classification:
- `python -m uacragent syllabus.pdf --doc-type syllabus --exam-format written`

Quick-start script:
- `python app.py`

By default, [app.py](app.py) runs against the included PDF fixture under `tests/outlines/`.

## Run (API)

Start the server:

- `PYTHONPATH=src uvicorn uacragent.api.main:app --reload`

Endpoints:

- `GET /health` — health check
- `POST /review` — generate a review with classified documents:
  ```json
  {
    "classified_files": {
      "syllabus": ["path/to/syllabus.pdf"],
      "lecture_note": ["path/to/notes.pdf"],
      "past_exam": ["path/to/exam1.pdf", "path/to/exam2.pdf"]
    },
    "exam_format": "written",
    "workspace_id": "default",
    "copy_to_workspace": true
  }
  ```
- `POST /review/simple` — legacy endpoint (all files treated as "other"):
  ```json
  {
    "file_paths": ["path/to/file.pdf"],
    "exam_format": "written",
    "workspace_id": "default"
  }
  ```

## Output

- Review files written to `data/<workspace_id>/outputs/` as `review_<timestamp>.<ext>`
- Uploaded files organized under `data/<workspace_id>/uploads/<doc_type>/`
- Vector DB persisted under `data/<workspace_id>/chroma_db/`

## Project structure

```
src/uacragent/
  __main__.py            CLI + GUI entry point
  agent/
    service.py           High-level orchestrator (AgentService)
    pipeline.py          RAG pipeline (load -> chunk -> embed -> plan -> write)
    prompts/
      planner.md         Prompt template for review plan generation
      reviewer.md        Prompt template for section writing
  api/
    main.py              FastAPI application factory
    routes.py            API endpoints (/health, /review, /review/simple)
    schemas.py           Request / response models with ClassifiedFiles
    deps.py              Dependency injection (settings, service singletons)
  domain/
    models.py            Core data models (ReviewPlan, SectionSpec)
    errors.py            Custom exception hierarchy
    types.py             Enums (DocumentType, ExamFormat, ExportFormat)
  infra/
    settings.py          Pydantic-based configuration (.env)
    loaders.py           Document loading with multi-stage type-specific splitting
    vectorstore.py       Chroma vector store with dedup
    llm.py               LLM client wrapper (Google Gemini)
    auth.py              API key validation
    workspace.py         Workspace directory management with classified folders
  export/
    markdown.py          Markdown export
    docx.py              DOCX export (python-docx)
    pdf.py               PDF export (fpdf2)
  ui/
    desktop/
      app.py             Tkinter desktop GUI with document type tabs
    web/                  (placeholder for future web UI)
app.py                   Script entry point (quick-start)
```
