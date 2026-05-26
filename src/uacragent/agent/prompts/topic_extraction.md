# Deep Analysis — Topic Extraction

You are performing a deep analysis of course materials to identify exam-relevant topics for: **{course_name}**.

## Course Materials Overview

{outline}

## Exam Context

- Exam type: {exam_type}
- Exam format: {exam_format}

---

# Task

Extract all major topics and concepts covered in these materials. For each topic, assess its likely importance for the upcoming exam based on how frequently it appears, how deeply it is covered, and its typical role in this type of exam.

For each topic, provide:

- **topic**: A clear, concise name (e.g. "Linear Regression", "Photosynthesis Pathways", "The French Revolution")
- **importance_score**: Integer 1–5 representing estimated exam weight
  - 5 = Core concept — almost certainly tested
  - 4 = Major topic — likely tested
  - 3 = Supporting concept — may be tested
  - 2 = Peripheral material — unlikely but possible
  - 1 = Background context — rarely examined directly
- **confidence**: Your confidence in this assessment as a decimal between 0.0 and 1.0

# Output Format

Return **valid JSON only** matching this schema exactly:

```
{{
  "topics": [
    {{"topic": "string", "importance_score": integer, "confidence": float}},
    ...
  ]
}}
```

Requirements:
- Produce 8–20 distinct topics.
- Cover the breadth of the course material — do not focus only on one area.
- Order does not matter in the JSON — results will be sorted by importance.
- Do not return an empty list.
- Do not include any text outside the JSON object.
