from __future__ import annotations

from pathlib import Path

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever

from uacragent.export.markdown import save_markdown
from uacragent.domain.models import ReviewPlan, SectionSpec
from uacragent.domain.errors import LLMError
from uacragent.infra.llm import LLMClient
from uacragent.infra.loaders import DocumentLoader
from uacragent.infra.settings import Settings
from uacragent.infra.vectorstore import build_retriever, get_or_create_vectorstore
from uacragent.infra.workspace import ensure_workspace_dirs, workspace_paths

def load_prompt(name: str) -> str:
    prompt_path = Path(__file__).parent / "prompts" / name
    return prompt_path.read_text(encoding="utf-8")

def build_outline(chunks: list[Document]) -> str:
    outline = ""
    for chunk in chunks:
        outline += chunk.page_content + "\n\n"
    return outline.strip()

def generate_plan(docs: list[Document], user_prefs: dict, llm_client: LLMClient) -> ReviewPlan:
    structured_llm = llm_client.with_structured_output(ReviewPlan)

    outline_text = "\n".join(d.page_content[:500] for d in docs[:5])

    prompt = ChatPromptTemplate.from_template(load_prompt("planner.md"))

    try:
        plan: ReviewPlan = structured_llm.invoke(
            prompt.format_messages(
                outline=outline_text,
                exam_format=user_prefs.get("exam_format", "unknown"),
            )
        )
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"Failed to generate plan: {exc}") from exc
    
    return plan

def write_section(section: SectionSpec, retriever: BaseRetriever, llm_client: LLMClient) -> str:
    query = section.title + " " + " ".join(section.key_topics)
    docs: list[Document] = retriever.invoke(query)

    context = "\n\n".join(d.page_content for d in docs)

    prompt = ChatPromptTemplate.from_template(load_prompt("reviewer.md"))

    resp = llm_client.invoke(prompt.format_messages(title=section.title, context=context))
    return getattr(resp, "content", str(resp))

def assemble_markdown(plan: ReviewPlan, sections: list[str]) -> str:
    md = f"# {plan.course_title} - Final Exam Review\n\n"
    for s in sections:
        md += s + "\n\n"
    return md


class AgentPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.loader = DocumentLoader(settings)
        self.llm_client = LLMClient(settings)

    def run_end_to_end(
        self,
        file_paths: list[str],
        exam_format: str,
        workspace_id: str = "default",
    ) -> tuple[ReviewPlan, str, str]:
        ws = workspace_paths(self.settings.workspace_root, workspace_id)
        ensure_workspace_dirs(ws)

        docs = self.loader.load_documents(file_paths)
        chunks = self.loader.split_documents(docs)

        vectorstore = get_or_create_vectorstore(chunks, self.settings, ws)
        retriever = build_retriever(vectorstore, self.settings)

        plan = generate_plan(docs, {"exam_format": exam_format}, self.llm_client)

        if not plan.sections:
            raise LLMError("Generated an empty review plan (no sections). Try again or adjust planner prompt.")

        section_texts: list[str] = []
        for section in plan.sections:
            section_texts.append(write_section(section, retriever, self.llm_client))

        final_md = assemble_markdown(plan, section_texts)
        md_path = save_markdown(final_md, ws)
        return plan, final_md, md_path