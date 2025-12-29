from pydantic import BaseModel
from typing import List

class SectionSpec(BaseModel):
    title: str
    key_topics: List[str]
    importance: int  # 1–5

class ReviewPlan(BaseModel):
    course_title: str
    exam_format: str
    sections: List[SectionSpec]
