import sys
from pathlib import Path

# Add project root and system folder to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "system"))

import base64
import json
import os
import re
import io
import wave
import tempfile
import shutil
import subprocess
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file
import cv_reader
import questions_generator
import chatbot
import grade_interview
import numpy as np


app = Flask(
    __name__,
    template_folder=str(PROJECT_ROOT / "templates"),
    static_folder=str(PROJECT_ROOT / "static")
)

UPLOAD_FOLDER = PROJECT_ROOT / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max limit


def get_candidate_dir(candidate_name: str) -> Path:
    safe_name = re.sub(r'[\\/*?:"<>|]', "", candidate_name).strip() or "Unknown_Candidate"
    cand_dir = UPLOAD_FOLDER / safe_name
    cand_dir.mkdir(parents=True, exist_ok=True)
    return cand_dir


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload_cv", methods=["POST"])
def upload_cv():
    if "cv_file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["cv_file"]
    if file.filename == "":
        return jsonify({"error": "Empty file name"}), 400

    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400

    temp_pdf_path = UPLOAD_FOLDER / file.filename
    file.save(temp_pdf_path)

    text = cv_reader.extract_text(temp_pdf_path)
    applicant = cv_reader.extract_applicant_info(text)

    raw_name = applicant.get("name") or "Unknown_Applicant"
    cand_dir = get_candidate_dir(raw_name)

    pdf_destination = cand_dir / file.filename
    temp_pdf_path.replace(pdf_destination)

    cv_json_path = cand_dir / f"{cand_dir.name}.json"
    with open(cv_json_path, "w", encoding="utf-8") as f:
        json.dump(applicant, f, indent=4, ensure_ascii=False)

    return jsonify({
        "status": "success",
        "candidate": raw_name,
        "candidate_folder": cand_dir.name,
        "applicant": applicant
    })


@app.route("/generate_questions", methods=["POST"])
def generate_questions():
    data = request.json or {}
    candidate_folder = data.get("candidate_folder")
    language = data.get("language", "English")

    if not candidate_folder:
        return jsonify({"error": "Missing candidate folder"}), 400

    cand_dir = UPLOAD_FOLDER / candidate_folder
    cv_json_path = cand_dir / f"{candidate_folder}.json"

    if not cv_json_path.exists():
        return jsonify({"error": "Applicant JSON profile not found"}), 404

    with open(cv_json_path, "r", encoding="utf-8") as f:
        resume = json.load(f)

    raw_questions = questions_generator.generate_questions(resume, language=language)
    clean_name = resume.get("name", candidate_folder).replace("\u00a0", " ").strip()

    output = {
        "candidate": clean_name,
        "language": language,
        "source_file": cv_json_path.name,
        "questions": raw_questions,
    }

    lang_slug = language.lower()
    questions_path = cand_dir / f"{candidate_folder}_questions_{lang_slug}.json"
    questions_generator.save_questions(output, questions_path)

    return jsonify({
        "status": "success",
        "questions_file": questions_path.name,
        "redirect": url_for("interview_page", candidate=candidate_folder, lang=lang_slug)
    })


@app.route("/interview/<candidate>/<lang>")
def interview_page(candidate, lang):
    cand_dir = UPLOAD_FOLDER / candidate
    questions_file = cand_dir / f"{candidate}_questions_{lang}.json"

    if not questions_file.exists():
        return f"Question file {questions_file.name} not found.", 404

    questions_data = chatbot.load_questions(questions_file)
    extracted_questions = chatbot.extract_questions(questions_data)

    return render_template(
        "interview.html",
        candidate=candidate,
        language=lang,
        questions=extracted_questions
    )


@app.route("/api/follow_up", methods=["POST"])
def api_follow_up():
    data = request.json or {}
    candidate_name = data.get("candidate_name")
    language = data.get("language")
    current_question = data.get("current_question")
    answer = data.get("answer")
    previous_answers = data.get("previous_answers", [])

    follow_up = chatbot.generate_follow_up(
        candidate_name=candidate_name,
        language=language,
        current_question=current_question,
        answer=answer,
        previous_answers=previous_answers
    )

    return jsonify({"follow_up": follow_up})


@app.route("/api/interview/transcribe-audio", methods=["POST"])
def transcribe_audio():
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files["audio"]
    
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_in:
        audio_file.save(tmp_in.name)
        input_path = tmp_in.name

    wav_16k_path = input_path + "_16k.wav"

    try:
        ffmpeg_bin = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"

        # Convert incoming audio blob to 16kHz Mono 16-bit PCM WAV
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i", input_path,
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            wav_16k_path
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode != 0:
            print(f"[FFmpeg Error Log]: {result.stderr}")
            return jsonify({"error": f"FFmpeg conversion failed: {result.stderr[:200]}"}), 500

        # Read samples directly using python standard wave module
        with wave.open(wav_16k_path, "rb") as wf:
            sample_rate = wf.getframerate()
            num_frames = wf.getnframes()
            frames = wf.readframes(num_frames)
            
            # Convert raw 16-bit PCM bytes to float32 normalized samples (-1.0 to 1.0)
            samples_int16 = np.frombuffer(frames, dtype=np.int16)
            samples_float32 = samples_int16.astype(np.float32) / 32768.0

        transcript = chatbot.transcribe_audio_sherpa(samples_float32, sample_rate)

        return jsonify({"transcript": transcript or ""})

    except Exception as e:
        print(f"[STT Error] {e}")
        return jsonify({"error": str(e)}), 500

    finally:
        for p in [input_path, wav_16k_path]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

@app.route("/api/tts", methods=["POST"])
def text_to_speech():
    data = request.json or {}
    text = data.get("text", "").strip()
    language = data.get("language", "English")

    if not text:
        return jsonify({"error": "No text provided"}), 400

    print(f"[TTS Request] Generating ({language}) audio for: '{text[:30]}...'")
    wav_bytes = chatbot.synthesize_sherpa_wav(text, language=language)

    if wav_bytes:
        audio_b64 = base64.b64encode(wav_bytes).decode("utf-8")
        return jsonify({
            "status": "success",
            "audio_data": f"data:audio/wav;base64,{audio_b64}"
        }), 200

    return jsonify({
        "status": "fallback",
        "use_browser_tts": True,
        "message": "Sherpa TTS generation failed."
    }), 200


@app.route("/api/save_answers", methods=["POST"])
def api_save_answers():
    data = request.json or {}
    candidate_folder = data.get("candidate_folder")
    language = data.get("language")
    answers = data.get("answers", [])

    cand_dir = UPLOAD_FOLDER / candidate_folder
    questions_file = cand_dir / f"{candidate_folder}_questions_{language.lower()}.json"

    output = {
        "candidate": candidate_folder,
        "source_questions": questions_file.name,
        "interview_language": language,
        "total_answered": len(answers),
        "answers": answers
    }

    answers_path = cand_dir / f"{candidate_folder}_answers.json"
    with open(answers_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=4, ensure_ascii=False)

    return jsonify({
        "status": "success",
        "redirect": url_for("report_page", candidate=candidate_folder)
    })


@app.route("/report/<candidate>")
def report_page(candidate):
    cand_dir = UPLOAD_FOLDER / candidate
    answers_path = cand_dir / f"{candidate}_answers.json"
    report_path = cand_dir / f"{candidate}_answers_report.json"

    if not answers_path.exists():
        return f"Answers file for {candidate} not found.", 404

    data = json.loads(answers_path.read_text(encoding="utf-8"))
    report = grade_interview.grade_interview(
        data=data,
        model=grade_interview.OLLAMA_MODEL,
        job_title="AI Engineer",
        job_requirements=None
    )
    
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    
    md_path = cand_dir / f"{candidate}_answers_report.md"
    grade_interview.write_markdown_report(report, md_path)

    return render_template("report.html", report=report)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)