# AI-Interviewer-Project
A fully automated website that runs technical interviews. Python files, including Flask web apps, handle each task in the interview process, and HTML, CSS and JavaScript build the site itself.

Applicants can make their own accounts to take the interview and check their results. Account info is stored in a SQL database.

<img width="1857" height="919" alt="image" src="https://github.com/user-attachments/assets/e13e4c5b-54e6-4e99-b518-dd3d9daaa45c" />


## The Full Interview Process
**Step 1: Resume parsing and data extraction**  
  Extracts raw text from PDF resumes and uses an LLM to parse it into clean, schema-compliant JSON. The output covers technical skills, work history, education, and notable projects.

<img width="972" height="637" alt="image" src="https://github.com/user-attachments/assets/678081cf-3a87-4e00-bdf8-3e34b9370656" />


**Step 2: Adaptive question synthesis**  
  Reads the JSON profile to judge the candidate's seniority and tech stack, then generates technical, behavioral and situational questions that probe their specific experience and any gaps. The website supports multiple languages.

<img width="889" height="876" alt="image" src="https://github.com/user-attachments/assets/561b95fa-0f6f-4881-91be-31354e47bef0" />


**Step 3: Interactive interview**  
  The conversational engine for the live session. It asks the questions one at a time, handles follow-ups and clarifications in real time, keeps session state, and outputs a full transcript of the candidate's responses.

<img width="838" height="754" alt="image" src="https://github.com/user-attachments/assets/409a2c67-2444-4814-993c-ac7c5ac12c73" />


**Step 4: Evaluation and report generation**  
  Checks the transcript against the generated questions and the candidate's background. Answers are scored on technical accuracy, problem-solving depth and communication clarity. The report includes structured metrics and hiring recommendations.

<img width="1073" height="667" alt="image" src="https://github.com/user-attachments/assets/fbb27151-f704-468e-9f6f-3177587abc8b" />

<img width="1003" height="596" alt="image" src="https://github.com/user-attachments/assets/0be3148a-ac4c-4cd8-bfec-dcd550f2d8a2" />

## Other features
**Personal accounts**  
  Interviewees can create accounts that store their interview results privately.

<img width="536" height="724" alt="image" src="https://github.com/user-attachments/assets/b46f536c-0770-45a9-aed8-e546c827636c" />


**Microphone testing**  
  Applicants can test their microphone on a separate page before the interview, so the session goes smoothly.

<img width="884" height="900" alt="image" src="https://github.com/user-attachments/assets/9b092519-197d-486d-9601-3506ce05b962" />


**Checking an interviewee's results**  
  The checker page shows the reports for an interviewee's session, including a score and comments on the answers.

<img width="994" height="470" alt="image" src="https://github.com/user-attachments/assets/6cbf4520-1ee8-4262-ba59-e22a55101f43" />

<img width="974" height="877" alt="image" src="https://github.com/user-attachments/assets/4fe44767-44a4-473e-bbb3-aaeece2d4dd7" />


## How to use the website
To try the website, download the setup files from the Releases page and run the ones for your OS. Each OS has two types: terminal-based and GUI-based. Then run `home_app.py` in the `apps` folder. You can also download the whole repo from GitHub.

No internet connection? `ai_interview_system.py` runs the entire process in the terminal in one go. You can also run the files separately, in this order:

[Resume PDF] ➔ `cv_reader.py` ➔ `questions_generator.py` ➔ `chatbot.py` ➔ `grade_interview.py` ➔ [Evaluation Report]

`interviewee_report_checker.py` prints the results of a chosen applicant's interview afterwards.

## Demo
You can see a demo of the project working at: https://drive.google.com/drive/folders/1HjoeWL_DjMnqFa8DV3Nbbc26OssA0fYs?usp=sharing
