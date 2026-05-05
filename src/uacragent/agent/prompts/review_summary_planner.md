# Task
You are creating a {exam_type} review summary for a specific university level course.

# Input
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
- course_title
- exam_format
- exam_type
- task_type: "review_summary"
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
  "sections": [
    {{
      "title": string,
      "key_topics": [string, string],
      "importance": 1
    }}
  ]
}}
