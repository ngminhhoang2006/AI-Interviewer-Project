# AI-Interviewer-Project
A fully automated website that runs technical interviews. Python files, including Flask web apps, handle each task in the interview process, and HTML, CSS and JavaScript build the site itself.

Applicants can make their own accounts to take the interview and check their results. Account info is stored in a SQL database.

<img width="1115" height="954" alt="image" src="https://github.com/user-attachments/assets/7d463d03-c84e-4dcf-8fd9-6e63478d30b4" />

## The Full Interview Process
**Step 1: Resume parsing and data extraction**  
  Extracts raw text from PDF resumes and uses an LLM to parse it into clean, schema-compliant JSON. The output covers technical skills, work history, education, and notable projects.

<img width="1143" height="700" alt="image" src="https://github.com/user-attachments/assets/932fbea2-db74-457f-928f-645a4c41c884" />

**Step 2: Adaptive question synthesis**  
  Reads the JSON profile to judge the candidate's seniority and tech stack, then generates technical, behavioral and situational questions that probe their specific experience and any gaps. The website supports multiple languages.

<img width="784" height="764" alt="image" src="https://github.com/user-attachments/assets/ed3f4ba3-c1fb-4743-8b0c-004e8d3bf368" />

**Step 3: Interactive interview**  
  The conversational engine for the live session. It asks the questions one at a time, handles follow-ups and clarifications in real time, keeps session state, and outputs a full transcript of the candidate's responses.

<img width="1112" height="932" alt="image" src="https://github.com/user-attachments/assets/1e2a491b-47ab-4763-b315-ab01947995f0" />

**Step 4: Evaluation and report generation**  
  Checks the transcript against the generated questions and the candidate's background. Answers are scored on technical accuracy, problem-solving depth and communication clarity. The report includes structured metrics and hiring recommendations.

<img width="1169" height="886" alt="image" src="https://github.com/user-attachments/assets/bccb9708-72da-4c55-8eb7-186ea69f347d" />

## Other features
**Personal accounts**  
  Interviewees can create accounts that store their interview results privately.

<img width="687" height="785" alt="image" src="https://github.com/user-attachments/assets/e11e22da-1928-406d-9f57-c728f1c856b5" />

**Microphone testing**  
  Applicants can test their microphone on a separate page before the interview, so the session goes smoothly.

<img width="692" height="784" alt="image" src="https://github.com/user-attachments/assets/00af66c0-af20-4c79-94e3-67d066073c29" />

**Checking an interviewee's results**  
  The checker page shows the reports for an interviewee's session, including a score and comments on the answers.

<img width="1158" height="803" alt="image" src="https://github.com/user-attachments/assets/fd911db0-f034-4b03-bb92-b2dc48aae6ed" />

<img width="1043" height="608" alt="image" src="https://github.com/user-attachments/assets/082e04fe-f388-4817-8a41-3772b2fccb7a" />


## Technical details
The AI and audio features run locally, so interview data stays on your machine.

**Question generation and grading: Ollama with Qwen3 8B**
Ollama serves Qwen3 8B locally. The model generates the technical, behavioral and situational questions from the candidate's profile (Step 2) and grades the transcript against those questions (Step 4). Running it locally means no API fees and no candidate data sent to a third-party service.

**Text-to-speech: sherpa-onnx**
sherpa-onnx reads each question aloud to the candidate. It runs speech models through ONNX Runtime on the local machine, so it needs no cloud service.

**Recording cleanup: noisereduce and webrtcvad**
Both libraries clean up the interviewee's recordings. webrtcvad wraps Google's WebRTC voice activity detector, which labels short audio frames as speech or non-speech. noisereduce uses spectral gating to suppress steady background noise such as fans or room hum.

## How to use the website
To try the website, download the setup files from the Releases page and run the ones for your OS. Each OS has two types: terminal-based and GUI-based. Then run `home_app.py` in the `apps` folder. You can also download the whole repo from GitHub.

No internet connection? `ai_interview_system.py` runs the entire process in the terminal in one go. You can also run the files separately, in this order:

[Resume PDF] ➔ `cv_reader.py` ➔ `questions_generator.py` ➔ `chatbot.py` ➔ `grade_interview.py` ➔ [Evaluation Report]

`interviewee_report_checker.py` prints the results of a chosen applicant's interview afterwards.

## Demo
You can see a demo of the project working at: https://drive.google.com/drive/folders/1HjoeWL_DjMnqFa8DV3Nbbc26OssA0fYs?usp=sharing
