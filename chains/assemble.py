from schemas.plan import ReviewPlan

def assemble_markdown(plan: ReviewPlan, sections: list[str]) -> str:
    md = f"# {plan.course_title} - Final Exam Review\n\n"
    for s in sections:
        md += s + "\n\n"
    return md
