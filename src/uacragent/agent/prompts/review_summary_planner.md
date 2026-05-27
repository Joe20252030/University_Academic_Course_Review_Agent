# Task
You are creating a {exam_type} review summary for a specific university level course.

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
Produce a structured study plan with the following fields:
- course_title: use the provided Course Name exactly
- exam_format, exam_type, task_type ("review_summary"), course_name, university_name, major, course_code, professor_name, semester, exam_duration, exam_info
- sections: each with title, key_topics (array of strings), importance (integer 1–5)

Constraints:
- Produce 8–12 sections.
- Each section must have 3–7 key_topics.
- Do not return an empty sections list.
- Tailor depth and scope to the exam type ({exam_type}). A quiz review should be focused and concise; a final exam review should be comprehensive.

## Language
{response_language}
