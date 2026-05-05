# Task
You are predicting the most likely topics and question types for an upcoming university {exam_type}. Analyze the course materials to identify high-probability exam content.

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
- task_type: "exam_prediction"
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
  "sections": [
    {{
      "title": string,
      "key_topics": [string, string],
      "importance": 1
    }}
  ]
}}
