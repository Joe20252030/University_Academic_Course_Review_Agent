# University Academic Course Review Agent (UACRAgent)

Generate a final-exam review document from a course outline (PDF/TXT/MD) using a RAG pipeline:

- Ingest course outline files (PDF, TXT, or Markdown)
- Chunk and embed into a local Chroma vector store
- Ask an LLM to create a structured review plan (JSON)
- For each planned section, retrieve relevant chunks and generate content
- Export to Markdown, DOCX, or PDF

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
- `CHUNK_SIZE=1000`
- `CHUNK_OVERLAP=150`
- `RETRIEVER_K=8`
- `WORKSPACE_ROOT=data`

## Run (Desktop GUI)

- `python -m uacragent --gui`
- `python -m uacragent` (launches the GUI when no file arguments are given)
- `python -m uacragent.ui.desktop.app`

The GUI lets you select files, choose exam format (written / mcq / mixed) and export format (Markdown / DOCX / PDF), and generate a review with one click. Works on macOS, Windows, and Linux.

## Run (CLI)

- `python app.py`
- `python -m uacragent outline.pdf --exam-format written --workspace-id default`

By default, [app.py](app.py) runs against the included PDF fixture under `tests/outlines/`.

To run on your own outline, either pass the path as a CLI argument or place it under [data/default/uploads/](data/default/uploads/) and update the file list in [app.py](app.py).

## Run (API, optional)

Start the server:

- `PYTHONPATH=src uvicorn uacragent.api.main:app --reload`

Endpoints:

- `GET /health` — health check
- `POST /review` — generate a review; JSON body: `{ "file_paths": [...], "exam_format": "written", "workspace_id": "default" }`

## Output

- Markdown / DOCX / PDF written to `data/<workspace_id>/outputs/` as `review_<timestamp>.<ext>`
- Vector DB persisted under `data/<workspace_id>/chroma_db/`

## Project structure

```
src/uacragent/
  __main__.py            CLI + GUI entry point
  agent/
    service.py           High-level orchestrator (AgentService)
    pipeline.py          RAG pipeline (plan -> retrieve -> write -> assemble)
    prompts/
      planner.md         Prompt template for review plan generation
      reviewer.md        Prompt template for section writing
  api/
    main.py              FastAPI application factory
    routes.py            API endpoints (/health, /review)
    schemas.py           Request / response models
    deps.py              Dependency injection (settings, service singletons)
  domain/
    models.py            Core data models (ReviewPlan, SectionSpec)
    errors.py            Custom exception hierarchy
    types.py             Enums (ExamFormat, ExportFormat)
  infra/
    settings.py          Pydantic-based configuration (.env)
    loaders.py           Document loading and chunking
    vectorstore.py       Chroma vector store with dedup
    llm.py               LLM client wrapper (Google Gemini)
    auth.py              API key validation
    workspace.py         Workspace directory management
  export/
    markdown.py          Markdown export
    docx.py              DOCX export (python-docx)
    pdf.py               PDF export (fpdf2)
  ui/
    desktop/
      app.py             Tkinter desktop GUI (cross-platform)
    web/                  (placeholder for future web UI)
app.py                   Script entry point (quick-start)
```
