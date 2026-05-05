# Task
Write a section of a mock {exam_type} for a university course.

# Input
## Course Information
- Course Name: {course_name}
- University: {university_name}
- Major / Department: {major}
- Course Code: {course_code}
- Professor: {professor_name}
- Semester: {semester}

## Section Title
{title}

## Key Topics to Cover
{key_topics}

## Context (from course materials)
{context}

## Exam Type
{exam_type}

## Exam Format
{exam_format}

## Additional Instructions
{extra_instructions}

# Output
Return **valid Markdown** containing:
- A section header with point allocation
- Realistic exam questions that match the {exam_format} format:
  - For "written": open-ended questions requiring detailed answers
  - For "mcq": multiple choice with 4 options each
  - For "mixed": a combination of both
- Questions should range from straightforward recall to application/analysis
- A clearly separated **Answer Key** section at the end with:
  - Full solutions for written questions
  - Correct answers with brief explanations for MCQ

Format the section as it would appear on an actual {exam_type} paper.
