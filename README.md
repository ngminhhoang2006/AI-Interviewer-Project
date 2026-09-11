# AI-Interviewer-Project
This is an end-to-end, fully automated pipeline designed to streamline the technical interview process using AI. This central orchestrator seamlessly connects four distinct modules into a unified workflow, taking a candidate from initial CV parsing to final performance evaluation in a single process:
- cv_reader — Parses raw PDF resumes into clean, structured JSON profile data.
- questions_generator — Synthesizes candidate profile data to generate tailored technical and situational questions.
- chatbot — Manages the interactive session, conducting the interview and recording candidate responses in real time.
- grade_interview — Evaluates response quality and generates a structured performance report.
