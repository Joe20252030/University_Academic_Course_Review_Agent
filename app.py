from config import get_settings
from ingest.loaders import load_documents
from indexing.splitter import split_documents
from indexing.vectorstore import get_or_create_vectorstore
from indexing.retriever import build_retriever
from chains.planner_chain import generate_plan
from chains.section_chain import write_section
from chains.assemble import assemble_markdown
from export.markdown import save_markdown
from export.docx import save_docx
from dotenv import load_dotenv
from langchain_core.documents import Document
from config import Settings
from schemas.plan import ReviewPlan
from langchain_core.vectorstores import VectorStore
from langchain_core.retrievers import BaseRetriever

FILE_PATHS = ["data/uploads/outline.pdf"]
TEST_FILE_PATHS = ["tests/fixtures/outlines/MGTA01 Course Outline - MShibaeva (Fall 2025) - updated.pdf"]

def main(file_paths: list[str], user_prefs: dict) -> None:
    settings: Settings = get_settings()

    # 1. Ingest
    docs: list[Document] = load_documents(file_paths)

    # 2. Chunk
    chunks: list[Document] = split_documents(docs, settings)

    # 3. Index
    vectorstore: VectorStore = get_or_create_vectorstore(chunks, settings)
    retriever: BaseRetriever = build_retriever(vectorstore, settings)

    # 4. Plan
    plan: ReviewPlan = generate_plan(docs, user_prefs, settings)

    # 5. Write sections
    section_texts: list[str] = []
    for section in plan.sections:
        section_md = write_section(section, retriever, settings)
        section_texts.append(section_md)

    # 6. Assemble
    final_md = assemble_markdown(plan, section_texts)

    # 7. Export
    md_path = save_markdown(final_md, settings)
    save_docx(final_md, settings)

    print(f"Review generated at {md_path}")

if __name__ == "__main__":
    #load_dotenv()
    main(TEST_FILE_PATHS, {"exam_format": "written"})
