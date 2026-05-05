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

## Additional Instructions
{extra_instructions}

# Output
Return **valid JSON only** that matches this schema:
- course_title: use the provided Course Name exactly
- exam_format
- exam_type
- task_type: "practice_booklet"
- course_name: copy from the provided Course Name
- university_name
- major
- course_code
- professor_name
- semester
- sections: title, key_topics (array), importance (integer 1-5)

Requirements:
- Produce 6-10 sections. Each section represents a topic area with practice problems.
- Each section must have 3-7 key_topics representing the specific skills to practice.
- Order sections from foundational to advanced.
- Weight importance based on how likely each topic is to appear on a {exam_type}.
- Do not return an empty sections list.
e.g.
{{
  "course_title": string,
  "exam_format": string,
  "exam_type": string,
  "task_type": "practice_booklet",
  "course_name": string,
  "university_name": string,
  "major": string,
  "course_code": string,
  "professor_name": string,
  "semester": string,
  "sections": [
    {{
      "title": string,
      "key_topics": [string, string],
      "importance": 1
    }}
  ]
}}
