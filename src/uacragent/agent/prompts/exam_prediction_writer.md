# Task
Write a **Part A prediction analysis section** for one high-priority topic area of an upcoming university {exam_type}.
This section is part of a two-part document: Part A is the topic-by-topic prediction analysis; Part B is the full predicted exam paper.

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
Return **valid Markdown** for this single analysis section, containing:
- **Prediction confidence**: High / Medium / Low with a one-line rationale
- **Why this topic is likely to appear**: brief reasoning grounded in the course materials
- **Key concepts to master**: bullet list of the most critical points
- **Predicted question styles**: types of questions to expect given the {exam_format} format
- **Suggested study approach**: how to prepare for this topic efficiently
- **Sample predicted questions** (2-3) with brief outline answers

Be concise and actionable — help the student allocate their study time effectively for the {exam_type}.

## Language
{response_language}
