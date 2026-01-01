# University Academic Course Review Agent (UACRAgent)

Generate a final-exam review document from a course outline (PDF/TXT/MD) using a simple RAG pipeline:

- Ingest course outline files
- Chunk and embed into a local Chroma vector store
- Ask an LLM to create a structured review plan (JSON)
- For each planned section, retrieve relevant chunks and generate a Markdown section
- Export to Markdown (DOCX/PDF exporters are currently placeholders)

## Requirements

- Python 3.10+ recommended
- A Google Gemini API key (used by default for both planning + section writing, and embeddings)

Important: running the pipeline will make paid model requests (LLM + embeddings) unless you replace/migrate the LLM/embeddings implementations.

## Install

1) Create/activate a virtual environment

- `python -m venv .venv`
- `source .venv/bin/activate`

2) Install dependencies

- `python -m pip install -r requirements.txt`

## Configure

This project uses environment variables (loaded from `.env` via `python-dotenv`) and [config.py](config.py) defaults.

Create a `.env` file in the repo root:

- `GOOGLE_API_KEY=...`

Optional overrides (these map to the `Settings` fields):

- `LLM_MODEL=gemini-2.5-pro`
- `EMBEDDING_MODEL=gemini-embedding-001`
- `CHUNK_SIZE=1000`
- `CHUNK_OVERLAP=150`
- `RETRIEVER_K=8`
- `CHROMA_DIR=data/chroma_db`
- `OUTPUT_DIR=data/outputs`

Notes:

- The code imports OpenAI adapters, but the default implementation uses Gemini.

## Run

By default, the entrypoint is currently configured to run against the included PDF fixture:

- [tests/fixtures/outlines/MGTA01%20Course%20Outline%20-%20MShibaeva%20(Fall%202025)%20-%20updated.pdf](tests/fixtures/outlines/MGTA01%20Course%20Outline%20-%20MShibaeva%20(Fall%202025)%20-%20updated.pdf)

To run on your own outline, put it under [data/uploads](data/uploads) (for example [data/uploads/outline.pdf](data/uploads/outline.pdf)) and update the `main(...)` call at the bottom of [app.py](app.py).

Run:

- `python app.py`

Notes:

- [app.py](app.py) currently calls `main(TEST_FILE_PATHS, {"exam_format": "written"})`.
- If you point it at your own file(s), it will embed + persist to Chroma under `data/chroma_db`.

## Output

- Markdown: written to [data/outputs](data/outputs) as `review_<timestamp>.md`
- DOCX/PDF: not implemented yet (see [export/docx.py](export/docx.py) and [export/pdf.py](export/pdf.py))
- Vector DB: persisted under [data/chroma_db](data/chroma_db)

## Example input

There is a sample outline PDF here:

- [tests/fixtures/outlines/MGTA01%20Course%20Outline%20-%20MShibaeva%20(Fall%202025)%20-%20updated.pdf](tests/fixtures/outlines/MGTA01%20Course%20Outline%20-%20MShibaeva%20(Fall%202025)%20-%20updated.pdf)

## Troubleshooting

- Missing API key: ensure `GOOGLE_API_KEY` is set (in your shell env or in `.env`).
- Dependency install errors on macOS: upgrade packaging tools with `python -m pip install -U pip setuptools wheel`.

## Tests (offline-safe)

The test suite is written to avoid making any outbound network calls (and will hard-fail if a test tries).

- `pytest`

## Project structure

- Entry: [app.py](app.py)
- Configuration: [config.py](config.py)
- Ingestion: [ingest/loaders.py](ingest/loaders.py)
- Indexing: [indexing/splitter.py](indexing/splitter.py), [indexing/vectorstore.py](indexing/vectorstore.py), [indexing/retriever.py](indexing/retriever.py)
- Chains: [chains/planner_chain.py](chains/planner_chain.py), [chains/section_chain.py](chains/section_chain.py), [chains/assemble.py](chains/assemble.py)
- Export: [export/markdown.py](export/markdown.py), [export/docx.py](export/docx.py)