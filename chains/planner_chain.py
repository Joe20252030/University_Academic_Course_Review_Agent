from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from config import Settings
from schemas.plan import ReviewPlan

def generate_plan(docs: list[Document], user_prefs: dict, settings: Settings) -> ReviewPlan:
    llm = ChatGoogleGenerativeAI(model=settings.LLM_MODEL, response_format="json")

    outline_text = "\n".join(d.page_content[:500] for d in docs[:5])

    prompt = ChatPromptTemplate.from_template("""
You are creating a final exam review summary for a specific university level course.

Course outline:
{outline}

Exam format: {exam_format}

Return a JSON format matching this schema:
- course_title
- exam_format
- sections: title, key_topics, importance (Use scale 1-5)
""")

    response = llm.invoke(prompt.format_messages(
        outline=outline_text,
        exam_format=user_prefs.get("exam_format", "unknown")
    ))

    return ReviewPlan.model_validate_json(response.content)
