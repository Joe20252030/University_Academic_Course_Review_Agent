# Task
Write an exam prediction analysis section for an upcoming university {exam_type}.

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
- **Prediction confidence**: High / Medium / Low
- **Why this topic is likely to appear**: brief reasoning based on course materials
- **Key concepts to master**: bullet list of the most critical points
- **Predicted question styles**: what types of questions to expect ({exam_format} format)
- **Suggested study approach**: how to prepare for this topic efficiently
- **Example predicted questions** (2-3) with outline answers

Focus on actionable predictions — help the student allocate their study time effectively for the {exam_type}.
