# University Academic Course Review Agent (UACRAgent)

Generate a final-exam review document from a course outline (PDF/TXT/MD) using a simple RAG pipeline:

- Ingest course outline files
- Chunk and embed into a local Chroma vector store
- Ask an LLM to create a structured review plan (JSON)
- For each planned section, retrieve relevant chunks and generate a Markdown section
- Export to Markdown + DOCX

## Requirements

- Python 3.9+ (3.10+ recommended)
- A Google Gemini API key (used by default)

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

1) Put your outline into [data/uploads](data/uploads) (default expected file is [data/uploads/outline.pdf](data/uploads/outline.pdf)).

2) Run:

- `python app.py`

The current entrypoint uses a hard-coded list in [app.py](app.py#L13):

- `FILE_PATHS = ["data/uploads/outline.pdf"]`

If your file has a different name/location, update that list.

## Output

- Markdown: written to [data/outputs](data/outputs) as `review_<timestamp>.md`
- DOCX: written to [data/outputs](data/outputs) as `review.docx`
- Vector DB: persisted under [data/chroma_db](data/chroma_db)

## Example input

There is a sample outline PDF here:

- [tests/fixtures/outlines/MGTA01%20Course%20Outline%20-%20MShibaeva%20(Fall%202025)%20-%20updated.pdf](tests/fixtures/outlines/MGTA01%20Course%20Outline%20-%20MShibaeva%20(Fall%202025)%20-%20updated.pdf)

## Troubleshooting

- Missing API key: ensure `GOOGLE_API_KEY` is set (in your shell env or in `.env`).
- Dependency install errors on macOS: upgrade packaging tools with `python -m pip install -U pip setuptools wheel`.

## Project structure

- Entry: [app.py](app.py)
- Configuration: [config.py](config.py)
- Ingestion: [ingest/loaders.py](ingest/loaders.py)
- Indexing: [indexing/splitter.py](indexing/splitter.py), [indexing/vectorstore.py](indexing/vectorstore.py), [indexing/retriever.py](indexing/retriever.py)
- Chains: [chains/planner_chain.py](chains/planner_chain.py), [chains/section_chain.py](chains/section_chain.py), [chains/assemble.py](chains/assemble.py)
- Export: [export/markdown.py](export/markdown.py), [export/docx.py](export/docx.py)