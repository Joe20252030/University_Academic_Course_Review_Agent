# Task
You are creating a final exam review summary for a specific university level course.

# Input
## Course outline
{outline}

## Exam Format
{exam_format}

# Output
Return **valid JSON only** that matches this schema:
- course_title
- exam_format
- sections: title, key_topics (array), importance (integer 1-5)

Requirements:
- Produce 8-12 sections.
- Each section must have 3-7 key_topics.
- Do not return an empty sections list.
e.g.
{{
  "course_title": string,
  "exam_format": string,
  "sections": [
    {{
      "title": string,
      "key_topics": [string, string],
      "importance": 1
    }}
  ]
}}