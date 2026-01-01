from schemas.plan import ReviewPlan, SectionSpec
from chains.assemble import assemble_markdown


def test_assemble_markdown_includes_title_and_sections() -> None:
	plan = ReviewPlan(
		course_title="MGTA01",
		exam_format="multiple choice",
		sections=[
			SectionSpec(title="One", key_topics=["A"], importance=3),
			SectionSpec(title="Two", key_topics=["B"], importance=4),
		],
	)

	sections = ["## One\n\nContent 1", "## Two\n\nContent 2"]
	md = assemble_markdown(plan, sections)

	assert md.startswith("# MGTA01 - Final Exam Review")
	assert "## One" in md
	assert "## Two" in md

