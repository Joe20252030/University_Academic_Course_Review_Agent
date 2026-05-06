# Task
Write a practice problem set for a university {exam_type} review booklet.

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

## Exam Duration
{exam_duration}

## Exam Information Sheet
{exam_info}

## Additional Instructions
{extra_instructions}

# Output
Return **valid Markdown** containing:
- A brief topic summary (2-3 sentences max)
- 5-8 practice problems of increasing difficulty (easy, medium, hard)
- For {exam_format} format: match the question style accordingly (written answers, multiple choice, or a mix)
- A complete solution key at the end of the section with step-by-step explanations

Label each problem with its difficulty level. For multiple choice questions, provide 4 options.
