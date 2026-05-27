# Task
You are creating a practice booklet for a university {exam_type}. The booklet should be a structured collection of practice problems and exercises organized by topic.

# Input
## Course Information
- Course Name: {course_name}
- University: {university_name}
- Major / Department: {major}
- Course Code: {course_code}
- Professor: {professor_name}
- Semester: {semester}

## Course outline
{outline}

## Exam Format
{exam_format}

## Exam Type
{exam_type}

## Exam Duration
{exam_duration}

## Exam Information Sheet
{exam_info}

## Additional Instructions
{extra_instructions}

# Output Requirements
Produce a structured practice plan with the following fields:
- course_title: use the provided Course Name exactly
- exam_format, exam_type, task_type ("practice_booklet"), course_name, university_name, major, course_code, professor_name, semester, exam_duration, exam_info
- sections: each with title, key_topics (array of strings), importance (integer 1–5)

Constraints:
- Produce 6–10 sections. Each section represents a topic area with practice problems.
- Each section must have 3–7 key_topics representing the specific skills to practice.
- Order sections from foundational to advanced.
- Weight importance based on how likely each topic is to appear on a {exam_type}.
- Do not return an empty sections list.

## Language
{response_language}
