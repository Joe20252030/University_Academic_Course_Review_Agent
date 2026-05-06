# University Academic Course Review Agent (UACRAgent)

Generate exam review materials from course documents using a RAG pipeline:

- Ingest course materials (PDF, TXT, Markdown, or DOCX)
- Classify documents by type for optimized processing
- Chunk documents using type-specific multi-stage splitting strategies
- Embed into a local Chroma vector store
- Ask an LLM to create a structured plan tailored to the chosen task
- For each planned section, retrieve relevant content and generate material in parallel
- Export to Markdown, DOCX, or PDF

## Task Types

The agent supports four distinct output modes:

| Task                 | Description                                                                     |
|----------------------|---------------------------------------------------------------------------------|
| **Review Summary**   | Comprehensive review with key concepts, definitions, tips, and sample questions |
| **Practice Booklet** | Structured collection of practice problems (easy/medium/hard) with solution key |
| **Mock Exam**        | Realistic exam paper with point allocations and a separate answer key           |
| **Exam Prediction**  | Analysis of likely exam topics with confidence levels and study strategies      |

Each task uses dedicated planner and writer prompts tuned for its output format.

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
- Enter a **course name** (required) and optional course details (university, major, course code, professor, semester)
- Add files to different document type categories (Syllabus, Lecture Notes, etc.)
- Choose a task (Review Summary, Practice Booklet, Mock Exam, Exam Prediction)
- Choose exam type (Quiz, Midterm, Final, Term Test, Other)
- Choose exam format (written / mcq / mixed)
- Provide extra instructions per task
- Enter optional **exam duration** (e.g. "2 hours") and **exam info sheet** text (allowed materials, covered topics, rules)
- Choose export format (Markdown / DOCX / PDF)
- Generate output with one click

Works on macOS, Windows, and Linux.

## Run (CLI)

`--course-name` is **required** for all CLI runs.

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

- Output files written to `data/<workspace_id>/outputs/` as `review_<timestamp>.<ext>`
- Uploaded files organized under `data/<workspace_id>/uploads/<doc_type>/`
- Vector DB persisted under `data/<workspace_id>/chroma_db/`
- The generated document header includes all provided course information fields

## Project structure

```
src/uacragent/
  __main__.py            CLI + GUI entry point
  agent/
    service.py           High-level orchestrator (AgentService)
    pipeline.py          RAG pipeline with task-type dispatch (parallel section writing)
    prompts/
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
    llm.py               LLM client wrapper (Google Gemini)
    auth.py              API key validation
    workspace.py         Workspace directory management with classified folders
  export/
    markdown.py          Markdown export
    docx.py              DOCX export (python-docx)
    pdf.py               PDF export (fpdf2, Unicode font auto-detection)
  ui/
    desktop/
      app.py             Tkinter desktop GUI
    web/                  (placeholder for future web UI)
tests/
  test_domain.py         Domain model and enum tests
  test_export.py         Markdown / DOCX / PDF export tests
  test_loaders.py        Document loading and splitting tests
  test_pipeline_utils.py Pipeline utility function tests
  test_workspace.py      Workspace path and directory tests
app.py                   Script entry point (quick-start)
```
