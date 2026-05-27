# Task
You are predicting the most likely topics and question types for an upcoming university {exam_type}. Analyze the course materials to identify high-probability exam content.

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
Produce a structured prediction plan with the following fields:
- course_title: use the provided Course Name exactly
- exam_format, exam_type, task_type ("exam_prediction"), course_name, university_name, major, course_code, professor_name, semester, exam_duration, exam_info
- sections: each with title, key_topics (array of strings), importance (integer 1–5)

Constraints:
- Produce 6–10 sections. Each section represents a predicted high-priority topic area.
- Each section must have 3–6 key_topics representing specific concepts likely to be tested.
- Importance reflects the predicted likelihood of appearing on the exam (5 = very likely).
- Prioritize topics that: appear repeatedly in materials, are emphasized in the syllabus, appear in past exams, or are flagged as important in lecture notes.
- Do not return an empty sections list.

## Language
{response_language}
