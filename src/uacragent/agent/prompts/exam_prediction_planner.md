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

## Additional Instructions
{extra_instructions}

# Output
Return **valid JSON only** that matches this schema:
- course_title: use the provided Course Name exactly
- exam_format
- exam_type
- task_type: "exam_prediction"
- course_name: copy from the provided Course Name
- university_name
- major
- course_code
- professor_name
- semester
- sections: title, key_topics (array), importance (integer 1-5)

Requirements:
- Produce 6-10 sections. Each section represents a predicted high-priority topic area.
- Each section must have 3-6 key_topics representing specific concepts likely to be tested.
- Importance reflects the predicted likelihood of appearing on the exam (5 = very likely).
- Prioritize topics that: appear repeatedly in materials, are emphasized in the syllabus, appear in past exams, or are flagged as important in lecture notes.
- Do not return an empty sections list.
e.g.
{{
  "course_title": string,
  "exam_format": string,
  "exam_type": string,
  "task_type": "exam_prediction",
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
