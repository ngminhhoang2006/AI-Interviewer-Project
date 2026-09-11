# AI-Interviewer-Project
This is an end-to-end, fully automated pipeline designed to streamline the technical interview process using AI. The pipeline uses 4 python files to perform 4 different tasks needed to perform the interview of an interviewee.

## Module Architecture & Responsibilities
**`cv_reader.py` — Resume Parsing & Data Extraction**  
  Extracts raw text from candidate PDF resumes and uses LLM-driven structured parsing to output clean, schema-compliant JSON. It normalizes key background details, including technical skill sets, professional work history, education, and notable projects.

**`questions_generator.py` — Adaptive Question Synthesis**  
  Consumes the structured JSON profile to analyze candidate seniority and technology stacks. It dynamically generates a customized set of technical, behavioral, and situational interview questions designed to probe specific background experience and potential gaps.

**`chatbot.py` — Interactive Interview Execution**  
  Serves as the conversational engine that conducts the live interview session. It presents synthesized questions to the candidate sequentially, processes user inputs, handles real-time follow-ups or clarifications, and maintains session state to output a complete candidate response transcript.

**`grade_interview.py` — Evaluation & Report Generation**  
  Analyzes the final interview transcript against the generated question set and baseline candidate context. It scores answers based on technical accuracy, problem-solving depth, and communication clarity, yielding a comprehensive evaluation report with structured metrics and hiring recommendations.

## How to use the module
We have included ai_interview_system.py that automates the entire process in one go. Alternatively, you can use each separate file in the following order:
[Resume PDF] ➔ cv_reader.py ➔ questions_generator.py ➔ chatbot.py ➔ grade_interview.py ➔ [Evaluation Report]

We have also included an interviewee_report_checker.py that prints out the results of the desired applicant's interview afterwards.

## Demo
You can see a demo of the project working at: https://drive.google.com/drive/folders/1HjoeWL_DjMnqFa8DV3Nbbc26OssA0fYs?usp=sharing









