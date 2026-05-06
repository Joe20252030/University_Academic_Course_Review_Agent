# Task
Generate **Part B: Predicted Exam Paper** for an upcoming university {exam_type}.
You are given a ranked list of predicted high-priority topics and supporting course material.
Produce a complete, realistic exam paper that a student could use as a full practice run.

# Input
## Course Information
- Course Name: {course_name}
- University: {university_name}
- Major / Department: {major}
- Course Code: {course_code}
- Professor: {professor_name}
- Semester: {semester}

## Predicted High-Priority Topics (ranked by likelihood)
{predicted_sections}

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
Return **valid Markdown** structured exactly as follows:

---

## Predicted Exam Paper

**Course:** {course_name}  
**Exam type:** {exam_type}  
**Duration:** {exam_duration}  
**Allowed materials:** (derive from exam_info, or write "Refer to exam information sheet" if not specified)  
**Total marks:** (assign a realistic total based on exam type and duration)

---

### Instructions
(Write 3-5 realistic exam instructions appropriate for the course and format.)

---

### Questions

Organise questions into parts or sections that mirror the {exam_format} format:
- **Written / mixed format**: use labelled parts (Part A, Part B, …) with short-answer, long-answer, and problem-solving questions.
- **MCQ format**: provide numbered multiple-choice questions with four options each (A–D).
- Distribute questions across the predicted topics, weighting them by importance score.
- Assign marks to each question or part.
- Total marks must match the declared total above.
- Questions should be specific, unambiguous, and at an appropriate university level.

---

### Answer Key / Marking Guide

For each question provide:
- The correct answer (or a model answer for written questions)
- Key marking criteria / mark allocation breakdown
- Common mistakes to avoid

---

Keep the tone and style consistent with a real university exam paper.
Do not add any commentary outside the exam paper structure.
