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

# Output
Return **valid JSON only** that matches this schema:
- course_title: use the provided Course Name exactly
- exam_format
- exam_type
- task_type: "review_summary"
- course_name: copy from the provided Course Name
- university_name
- major
- course_code
- professor_name
- semester
- exam_duration
- exam_info
- sections: title, key_topics (array), importance (integer 1-5)

Requirements:
- Produce 8-12 sections.
- Each section must have 3-7 key_topics.
- Do not return an empty sections list.
- Tailor the depth and scope to the exam type ({exam_type}). For example, a quiz review should be more focused and concise, while a final exam review should be comprehensive.
e.g.
{{
  "course_title": string,
  "exam_format": string,
  "exam_type": string,
  "task_type": "review_summary",
  "course_name": string,
  "university_name": string,
  "major": string,
  "course_code": string,
  "professor_name": string,
  "semester": string,
  "exam_duration": string,
  "exam_info": string,
  "sections": [
    {{
      "title": string,
      "key_topics": [string, string],
      "importance": 1
    }}
  ]
}}
