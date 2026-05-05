# Task
You are creating a realistic mock {exam_type} for a university course. The mock exam should mirror the format, difficulty, and coverage of a real {exam_type}.

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
- task_type: "mock_exam"
- sections: title, key_topics (array), importance (integer 1-5)

Requirements:
- Produce 4-8 sections. Each section represents a distinct part or question group of the mock exam.
- Each section must have 2-5 key_topics representing the concepts tested.
- Importance reflects the point weight of that section (5 = highest weight).
- Structure it like a real {exam_type}: e.g. Part A: Short Answer, Part B: Long Answer, Part C: MCQ.
- Do not return an empty sections list.
e.g.
{{
  "course_title": string,
  "exam_format": string,
  "exam_type": string,
  "task_type": "mock_exam",
  "sections": [
    {{
      "title": string,
      "key_topics": [string, string],
      "importance": 1
    }}
  ]
}}
