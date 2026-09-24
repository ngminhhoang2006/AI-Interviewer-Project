# AI-Interviewer-Project
This is an end-to-end, fully automated website designed to streamline the technical interview process using AI. The website uses python files (including Flask web apps) to perform the different tasks needed to perform the interview of an interviewee, as well as HTML, CSS and Javascript to build the format of the website.

The website also allows applicants to make their own accounts to get their own personalized experience of using the website, doing the interview and checking their results. All of their accounts' info are stored securely in a SQL database

<img width="1857" height="919" alt="image" src="https://github.com/user-attachments/assets/e13e4c5b-54e6-4e99-b518-dd3d9daaa45c" />


## The Full Interview Process
**STEP 1: Resume Parsing & Data Extraction**  
  Extracts raw text from candidate PDF resumes and uses LLM-driven structured parsing to output clean, schema-compliant JSON. It normalizes key background details, including technical skill sets, professional work history, education, and notable projects.

<img width="972" height="637" alt="image" src="https://github.com/user-attachments/assets/678081cf-3a87-4e00-bdf8-3e34b9370656" />


**STEP 2: Adaptive Question Synthesis**  
  Consumes the structured JSON profile to analyze candidate seniority and technology stacks. It dynamically generates a customized set of technical, behavioral, and situational interview questions designed to probe specific background experience and potential gaps.

<img width="893" height="575" alt="image" src="https://github.com/user-attachments/assets/0e6c9195-7eb3-4a81-b2bf-4eb05c9c9388" />


**STEP 3:  — Interactive Interview Execution**  
  Serves as the conversational engine that conducts the live interview session. It presents synthesized questions to the candidate sequentially, processes user inputs, handles real-time follow-ups or clarifications, and maintains session state to output a complete candidate response transcript.

<img width="838" height="754" alt="image" src="https://github.com/user-attachments/assets/409a2c67-2444-4814-993c-ac7c5ac12c73" />


**STEP 4:  — Evaluation & Report Generation**  
  Analyzes the final interview transcript against the generated question set and baseline candidate context. It scores answers based on technical accuracy, problem-solving depth, and communication clarity, yielding a comprehensive evaluation report with structured metrics and hiring recommendations.

<img width="1073" height="667" alt="image" src="https://github.com/user-attachments/assets/fbb27151-f704-468e-9f6f-3177587abc8b" />

<img width="1003" height="596" alt="image" src="https://github.com/user-attachments/assets/0be3148a-ac4c-4cd8-bfec-dcd550f2d8a2" />

## Other features
**Microphone testing**  
  Before the interview, applicants can test their microphones on a separate page to make sure their interviews goes smoothly.

<img width="884" height="900" alt="image" src="https://github.com/user-attachments/assets/9b092519-197d-486d-9601-3506ce05b962" />


**Check an interviewee's results**  
  Use the checker page to see the reports of an interviewee's interview session. The reports include a score, and comments on the answers.

<img width="994" height="470" alt="image" src="https://github.com/user-attachments/assets/6cbf4520-1ee8-4262-ba59-e22a55101f43" />

<img width="974" height="877" alt="image" src="https://github.com/user-attachments/assets/4fe44767-44a4-473e-bbb3-aaeece2d4dd7" />


## How to use the website
To see and use the website for yourself, download the files, and run home_app.py in the "apps" folder.

For those who don't have an internet connection, We have included ai_interview_system.py that automates the entire process in the terminal/command prompt in one go. Alternatively, you can use each separate file in the following order:
[Resume PDF] ➔ cv_reader.py ➔ questions_generator.py ➔ chatbot.py ➔ grade_interview.py ➔ [Evaluation Report]

We have also included an interviewee_report_checker.py that prints out the results of the desired applicant's interview afterwards.

## Demo
You can see a demo of the project working at: https://drive.google.com/drive/folders/1HjoeWL_DjMnqFa8DV3Nbbc26OssA0fYs?usp=sharing









