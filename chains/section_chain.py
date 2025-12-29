from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from config import Settings
from schemas.plan import SectionSpec
from langchain_core.retrievers import BaseRetriever
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document

def write_section(section: SectionSpec, retriever: BaseRetriever, settings: Settings) -> str:
    llm = ChatGoogleGenerativeAI(model=settings.LLM_MODEL)

    query = section.title + " " + " ".join(section.key_topics)
    docs: list[Document] = retriever.invoke(query)

    context = "\n\n".join(d.page_content for d in docs)

    prompt = ChatPromptTemplate.from_template("""
Write a final-exam review section.

Section title: {title}
Context:
{context}

Include:
- key concepts
- definitions
- common mistakes
- exam-style tips

Markdown format.
""")

    return llm.invoke(
        prompt.format_messages(title=section.title, context=context)
    ).content
