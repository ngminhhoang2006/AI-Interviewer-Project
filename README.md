# AI-Interviewer-Project
A fully automated website that runs technical interviews. Python files, including Flask web apps, handle each task in the interview process, and HTML, CSS and JavaScript build the site itself.

Applicants can make their own accounts to take the interview and check their results. Account info is stored in a SQL database.

<img width="990" height="903" alt="image" src="https://github.com/user-attachments/assets/460d4a94-0827-4fd1-95d5-a9fcb136aec4" />


## The Full Interview Process
**Step 1: Resume parsing and data extraction**  
  Extracts raw text from PDF resumes and uses an LLM to parse it into clean, schema-compliant JSON. The output covers technical skills, work history, education, and notable projects.

<img width="1132" height="575" alt="image" src="https://github.com/user-attachments/assets/937379e0-0b2f-4d8c-b39e-7563651aacf2" />


**Step 2: Adaptive question synthesis**  
  Reads the JSON profile to judge the candidate's seniority and tech stack, then generates technical, behavioral and situational questions that probe their specific experience and any gaps. The website supports multiple languages.

<img width="1097" height="869" alt="image" src="https://github.com/user-attachments/assets/cac6f254-3843-4893-89e6-41e3a82004c2" />


**Step 3: Interactive interview**  
  The conversational engine for the live session. It asks the questions one at a time, handles follow-ups and clarifications in real time, keeps session state, and outputs a full transcript of the candidate's responses.

<img width="1078" height="927" alt="image" src="https://github.com/user-attachments/assets/aa4db5b8-f336-4b69-b672-b28fe4a728e1" />


**Step 4: Evaluation and report generation**  
  Checks the transcript against the generated questions and the candidate's background. Answers are scored on technical accuracy, problem-solving depth and communication clarity. The report includes structured metrics and hiring recommendations.

<img width="1132" height="848" alt="image" src="https://github.com/user-attachments/assets/68c4b2b8-cf19-4b03-a222-ac6d3b0f3978" />

## Other features
**Personal accounts**  
  Interviewees can create accounts that store their interview results privately.

<img width="626" height="625" alt="image" src="https://github.com/user-attachments/assets/fcde278d-a51c-4a15-8179-f349bf72a8cd" />


**Microphone testing**  
  Applicants can test their microphone on a separate page before the interview, so the session goes smoothly.

<img width="753" height="886" alt="image" src="https://github.com/user-attachments/assets/4095f47f-ebca-41dd-997e-c4b73bde7814" />


**Checking an interviewee's results**  
  The checker page shows the reports for an interviewee's session, including a score and comments on the answers.

<img width="1153" height="654" alt="image" src="https://github.com/user-attachments/assets/c97b4e51-da57-4a5e-9f27-84a7dae3b65c" />

<img width="1123" height="700" alt="image" src="https://github.com/user-attachments/assets/badb5972-3c69-4e77-b335-2beed25012d7" />

<img width="1050" height="587" alt="image" src="https://github.com/user-attachments/assets/1ee5c863-ba26-4ae8-9864-26e8e3fdd156" />

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
