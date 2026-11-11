import sys
from pathlib import Path

# system/ holds the pipeline modules imported below.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "system"))

import base64
import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from flask import Flask, render_template, request, jsonify, url_for, abort
import cv_reader
import questions_generator
import chatbot
import grade_interview
import numpy as np

from flask_login import current_user, login_required
from models import db, InterviewResult, ApplicantProfile
import score_store
from i18n import t


app = Flask(
    __name__,
    template_folder=str(PROJECT_ROOT / "templates"),
    static_folder=str(PROJECT_ROOT / "static")
)

UPLOAD_FOLDER = PROJECT_ROOT / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

# Interview languages for the Step 2 dropdown.
#   value: English name sent to the LLM and speech code; lower-cased into file names and URLs, so one word.
#   tag: BCP-47 tag for the browser voice, used when Sherpa has no voice for the language.
# A new language also needs an entry in WHISPER_LANG_CODES in system/chatbot.py.
# An offline voice is used if system/sherpa_models/tts_<value lower-cased>/ exists (system/download_models.py).
SUPPORTED_LANGUAGES = [
    {"value": "English",    "label": "English",                  "tag": "en-US"},
    {"value": "Vietnamese", "label": "Vietnamese (Tiếng Việt)",  "tag": "vi-VN"},
    {"value": "Chinese",    "label": "Chinese (中文)",            "tag": "zh-CN"},
    {"value": "Japanese",   "label": "Japanese (日本語)",         "tag": "ja-JP"},
    {"value": "Korean",     "label": "Korean (한국어)",           "tag": "ko-KR"},
    {"value": "Spanish",    "label": "Spanish (Español)",        "tag": "es-ES"},
    {"value": "French",     "label": "French (Français)",        "tag": "fr-FR"},
    {"value": "German",     "label": "German (Deutsch)",         "tag": "de-DE"},
    {"value": "Portuguese", "label": "Portuguese (Português)",   "tag": "pt-BR"},
    {"value": "Italian",    "label": "Italian (Italiano)",       "tag": "it-IT"},
    {"value": "Russian",    "label": "Russian (Русский)",        "tag": "ru-RU"},
    {"value": "Hindi",      "label": "Hindi (हिन्दी)",             "tag": "hi-IN"},
    {"value": "Indonesian", "label": "Indonesian (Bahasa Indonesia)", "tag": "id-ID"},
    {"value": "Arabic",     "label": "Arabic (العربية)",          "tag": "ar-SA"},
    {"value": "Turkish",    "label": "Turkish (Türkçe)",         "tag": "tr-TR"},
    {"value": "Polish",     "label": "Polish (Polski)",          "tag": "pl-PL"},
    {"value": "Ukrainian",  "label": "Ukrainian (Українська)",   "tag": "uk-UA"},
    {"value": "Thai",       "label": "Thai (ไทย)",                "tag": "th-TH"},
]
LANGUAGE_BY_KEY = {l["value"].lower(): l["value"] for l in SUPPORTED_LANGUAGES}
LANGUAGE_TAGS = {l["value"].lower(): l["tag"] for l in SUPPORTED_LANGUAGES}


@app.context_processor
def inject_languages():
    """Makes `interview_languages` available to every template."""
    return {"interview_languages": SUPPORTED_LANGUAGES}


def get_candidate_dir(candidate_name: str) -> Path:
    safe_name = re.sub(r'[\\/*?:"<>|]', "", candidate_name).strip() or "Unknown_Candidate"
    cand_dir = UPLOAD_FOLDER / safe_name
    cand_dir.mkdir(parents=True, exist_ok=True)
    return cand_dir


CV_LIST_FIELDS = ["education", "experience", "projects", "skills", "certifications", "awards"]


def ensure_applicant_table():
    """Create applicant_profiles if this database doesn't have it yet (fresh or older install).
    No-op when the table exists, so it is safe to call every time."""
    ApplicantProfile.__table__.create(bind=db.engine, checkfirst=True)


def save_applicant_profile(user_id, result_id, cv_json_path):
    """Create/update the applicant_profiles row linked to this user and interview result."""
    if not cv_json_path.exists():
        return
    ensure_applicant_table()
    cv = json.loads(cv_json_path.read_text(encoding="utf-8"))
    profile = ApplicantProfile.query.filter_by(interview_result_id=result_id).first()
    if profile is None:
        profile = ApplicantProfile(user_id=user_id, interview_result_id=result_id)
        db.session.add(profile)
    profile.full_name = (cv.get("name") or "").replace("\u00a0", " ").strip() or None
    profile.email = cv.get("email")
    profile.phone = cv.get("phone")
    profile.address = (cv.get("address") or "").replace("\u00a0", " ").strip() or None
    profile.age = cv.get("age")
    for field in CV_LIST_FIELDS:
        setattr(profile, field, json.dumps(cv.get(field) or [], ensure_ascii=False))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload_cv", methods=["POST"])
def upload_cv():
    if "cv_file" not in request.files:
        return jsonify({"error": t("e.no_file")}), 400

    file = request.files["cv_file"]
    if file.filename == "":
        return jsonify({"error": "Empty file name"}), 400

    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": t("e.pdf_only")}), 400

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
        "text_extracted": bool(text.strip()),
        "name_detected": bool(applicant.get("name")),
        "applicant": applicant
    })


@app.route("/generate_questions", methods=["POST"])
def generate_questions():
    data = request.json or {}
    candidate_folder = data.get("candidate_folder")
    # Only accept languages from SUPPORTED_LANGUAGES (also keeps odd values out of file names)
    language = LANGUAGE_BY_KEY.get(str(data.get("language") or "English").strip().lower())

    if not candidate_folder:
        return jsonify({"error": "Missing candidate folder"}), 400
    if not language:
        return jsonify({"error": f"Unsupported language: {data.get('language')}"}), 400

    job_position = questions_generator.clean_job_position(data.get("job_position"))
    if not job_position:
        return jsonify({"error": t("js.need_position")}), 400

    cand_dir = UPLOAD_FOLDER / candidate_folder
    cv_json_path = cand_dir / f"{candidate_folder}.json"

    if not cv_json_path.exists():
        return jsonify({"error": "Applicant JSON profile not found"}), 404

    with open(cv_json_path, "r", encoding="utf-8") as f:
        resume = json.load(f)

    # The name can be corrected on the setup page (e.g. when it could not be read from the PDF)
    typed_name = re.sub(r"\s+", " ", str(data.get("candidate_name") or "")).strip()[:100]
    if typed_name and typed_name != (resume.get("name") or ""):
        resume["name"] = typed_name
        with open(cv_json_path, "w", encoding="utf-8") as f:
            json.dump(resume, f, indent=4, ensure_ascii=False)

    # Generation takes a while, so it runs in the background and the setup page follows its progress
    lang_slug = language.lower()
    questions_path = cand_dir / f"{candidate_folder}_questions_{lang_slug}.json"
    job_id = _start_generation_job(
        resume, language, job_position, candidate_folder, cv_json_path, questions_path,
        redirect_url=url_for("mic_test_page", candidate=candidate_folder, lang=lang_slug))

    return jsonify({
        "status": "started",
        "job_id": job_id,
        "status_url": url_for("api_generation_status", job_id=job_id),
    })


# ---- Question generation runs in a background thread so the browser can show a time estimate ------
# One job per click, kept in memory (single-process server) and looked up by a random id.
GENERATION_JOBS = {}
GENERATION_LOCK = threading.Lock()
GENERATION_STATS_FILE = PROJECT_ROOT / "generation_stats.json"   # timings of earlier runs, for the estimate
GENERATION_STATS_KEEP = 5            # how many earlier runs the estimate averages
DEFAULT_EXPECTED_TOKENS = 1500       # used for the progress bar until there is a history of earlier runs


def _stats_key(language):
    return f"{questions_generator.QUESTION_MODEL}|{language}"


def _load_generation_stats():
    try:
        return json.loads(GENERATION_STATS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _expected_generation(language):
    """Average size and speed of the last few runs for this model and language, or None if there are none."""
    runs = _load_generation_stats().get(_stats_key(language)) or []
    if not runs:
        return None
    try:
        return {k: sum(r[k] for r in runs) / len(runs) for k in ("tokens", "ttft", "rate")}
    except (KeyError, TypeError):
        return None


def _record_generation(job):
    """Remembers how long this run took (call with GENERATION_LOCK held)."""
    n, first, last, began = job["tokens"], job["first_token_at"], job["last_token_at"], job["attempt_started"]
    if n < 20 or first is None or last is None or last - first < 0.5:
        return
    stats = _load_generation_stats()
    runs = stats.get(_stats_key(job["language"]), [])
    runs.append({"tokens": n, "ttft": first - began, "rate": (n - 1) / (last - first)})
    stats[_stats_key(job["language"])] = runs[-GENERATION_STATS_KEEP:]
    try:
        GENERATION_STATS_FILE.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"[warn] could not save generation timings: {e}")


def _estimate_generation(job, now):
    """Returns (percent 0-100, seconds left or None) for a running job."""
    exp, n = job["expected"], job["tokens"]
    exp_tokens = exp["tokens"] if exp else DEFAULT_EXPECTED_TOKENS
    exp_tokens = max(exp_tokens, n * 1.15 + 1)       # never look finished while words are still arriving
    percent = min(n / exp_tokens, 0.97) * 100

    if job["first_token_at"] is None:                # the model is still loading / reading the CV
        if not exp:
            return percent, None
        waited = now - job["attempt_started"]
        return percent, max(0.0, exp["ttft"] - waited) + exp_tokens / exp["rate"]

    spent = now - job["first_token_at"]
    if n >= 5 and spent >= 0.5:
        rate = n / spent                              # this run's own speed
    elif exp:
        rate = exp["rate"]
    else:
        return percent, None
    return percent, max(0.0, (exp_tokens - n) / rate)


def _run_generation_job(job, resume, language, job_position, candidate_folder, cv_json_path, questions_path):
    def on_progress(attempt, tokens):
        now = time.monotonic()
        with GENERATION_LOCK:
            if attempt != job["attempt"]:             # a new attempt: start counting again
                job.update(attempt=attempt, tokens=0, attempt_started=now, first_token_at=None, last_token_at=None)
            if tokens:
                job["tokens"], job["last_token_at"] = tokens, now
                if job["first_token_at"] is None:
                    job["first_token_at"] = now

    try:
        raw_questions = questions_generator.generate_questions(
            resume, language=language, job_position=job_position, progress=on_progress)
        clean_name = (resume.get("name") or candidate_folder).replace("\u00a0", " ").strip()
        output = {
            "candidate": clean_name,
            "language": language,
            "job_position": job_position,
            "source_file": cv_json_path.name,
            "questions": raw_questions,
        }
        questions_generator.save_questions(output, questions_path)
        with GENERATION_LOCK:
            _record_generation(job)
            job["state"] = "done"
    except Exception as e:
        app.logger.exception("Question generation failed")
        message = questions_generator.describe_generation_error(e, language)
        with GENERATION_LOCK:
            job["state"], job["error"] = "error", message


def _start_generation_job(resume, language, job_position, candidate_folder, cv_json_path, questions_path, redirect_url):
    now = time.monotonic()
    job = {
        "state": "running", "error": None, "redirect": redirect_url, "language": language,
        "attempt": 0, "tokens": 0, "attempt_started": now, "first_token_at": None, "last_token_at": None,
        "expected": _expected_generation(language), "created": now,
    }
    job_id = uuid.uuid4().hex
    with GENERATION_LOCK:
        for old_id in [k for k, j in GENERATION_JOBS.items() if now - j["created"] > 3600]:
            del GENERATION_JOBS[old_id]               # forget jobs older than an hour
        GENERATION_JOBS[job_id] = job
    threading.Thread(
        target=_run_generation_job,
        args=(job, resume, language, job_position, candidate_folder, cv_json_path, questions_path),
        daemon=True).start()
    return job_id


@app.route("/api/generation_status/<job_id>")
def api_generation_status(job_id):
    """Progress of a question-generation job, polled by static/js/setup.js."""
    with GENERATION_LOCK:
        job = GENERATION_JOBS.get(job_id)
        if job is None:
            return jsonify({"state": "missing"})
        if job["state"] == "running":
            percent, eta = _estimate_generation(job, time.monotonic())
            body = {"state": "running", "percent": round(percent), "eta": eta}
        elif job["state"] == "done":
            body = {"state": "done", "percent": 100, "eta": 0, "redirect": job["redirect"]}
        else:
            body = {"state": "error", "error": job["error"]}
    response = jsonify(body)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/mic_test/<candidate>/<lang>")
def mic_test_page(candidate, lang):
    return render_template(
        "mic_test.html",
        candidate=candidate,
        language=lang
    )


@app.route("/interview/<candidate>/<lang>")
@login_required
def interview_page(candidate, lang):
    cand_dir = UPLOAD_FOLDER / candidate
    questions_file = cand_dir / f"{candidate}_questions_{lang}.json"

    if not questions_file.exists():
        # Don't echo URL parts back as HTML (that was a reflected XSS)
        abort(404)

    questions_data = chatbot.load_questions(questions_file)
    extracted_questions = chatbot.extract_questions(questions_data)

    return render_template(
        "interview.html",
        candidate=candidate,
        language=lang,
        language_tag=LANGUAGE_TAGS.get(lang.lower(), "en-US"),
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
    language = request.form.get("language", "English")
    # The question currently being answered, used as context for LLM cleanup
    current_question = request.form.get("current_question", "")

    audio_bytes = audio_file.read()
    SAMPLE_RATE = 16000

    try:
        ffmpeg_bin = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"

        # webm in via stdin, raw 16-bit PCM out via stdout, so no temp files.
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i", "pipe:0",
            "-f", "s16le",
            "-ac", "1",
            "-ar", str(SAMPLE_RATE),
            "pipe:1"
        ]

        result = subprocess.run(
            cmd,
            input=audio_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        if result.returncode != 0:
            err_text = result.stderr.decode("utf-8", errors="replace")
            print(f"[FFmpeg Error Log]: {err_text}")
            return jsonify({"error": f"FFmpeg conversion failed: {err_text[:200]}"}), 500

        samples_int16 = np.frombuffer(result.stdout, dtype=np.int16)
        samples_float32 = samples_int16.astype(np.float32) / 32768.0

        # Denoises, then routes to Parakeet or Whisper by language.
        raw_transcript = chatbot.transcribe_audio_sherpa(samples_float32, SAMPLE_RATE, language=language)

        # Ollama pass fixes misheard words and punctuation without changing the meaning.
        corrected_transcript = chatbot.correct_transcript(
            raw_transcript,
            question_context=current_question,
            language=language
        )

        return jsonify({
            "transcript": corrected_transcript or "",
            "raw_transcript": raw_transcript or ""
        })

    except Exception as e:
        print(f"[STT Error] {e}")
        return jsonify({"error": str(e)}), 500

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
        "message": chatbot.TTS_LAST_ERROR.get(str(language).lower().strip(), "Sherpa TTS generation failed.")
    }), 200


@app.route("/api/save_answers", methods=["POST"])
def api_save_answers():
    data = request.json or {}
    candidate_folder = data.get("candidate_folder")
    language = data.get("language")
    answers = data.get("answers", [])

    cand_dir = UPLOAD_FOLDER / candidate_folder
    questions_file = cand_dir / f"{candidate_folder}_questions_{language.lower()}.json"

    # Carry the job position chosen on the setup page over to the answers file (used for grading)
    job_position = ""
    try:
        job_position = json.loads(questions_file.read_text(encoding="utf-8")).get("job_position", "")
    except (OSError, ValueError):
        pass

    output = {
        "candidate": candidate_folder,
        "job_position": job_position,
        "source_questions": questions_file.name,
        "interview_language": language,
        "total_answered": len(answers),
        "answers": answers
    }

    answers_path = cand_dir / f"{candidate_folder}_answers.json"
    with open(answers_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=4, ensure_ascii=False)

    # New answers: forget any earlier grading job so /report/<candidate> grades these ones
    with GRADING_LOCK:
        GRADING_JOBS.pop(candidate_folder, None)

    return jsonify({
        "status": "success",
        "redirect": url_for("report_page", candidate=candidate_folder)
    })

def _as_score(value):
    """Turns a score from the grader (8, 8.0, "8", "8/10", None) into a float, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.search(r"\d+(?:\.\d+)?", value)
        return float(m.group()) if m else None
    return None


def extract_report_scores(report):
    """(overall_score, average_per_question_score, feedback) from grade_interview()'s report.
    The grader returns {"average_score": ..., "overall": {"overall_score": ..., "summary": ...}}."""
    overall = report.get("overall") if isinstance(report.get("overall"), dict) else {}
    overall_score = _as_score(overall.get("overall_score", report.get("overall_score")))
    avg_score = _as_score(report.get(
        "average_score", report.get("average_per_question_score", report.get("avg_score"))))
    feedback = (overall.get("summary") or report.get("summary") or report.get("overall_feedback")
                or "Completed interview evaluation.")
    return overall_score, avg_score, str(feedback)


def save_interview_scores(user_id, candidate, language, report):
    """Stores the grades in interview_results and VERIFIES they really are in the database file.
    1) normal save through SQLAlchemy;
    2) if that raises, or the stored scores don't match the report: a direct SQLite write, then the
       backfill (reads the report files on disk).
    Never raises. Returns (interview_result_id or None, status) with status "saved",
    "saved_via_fallback" or "failed"."""
    overall, avg, feedback = extract_report_scores(report)
    db_file = db.engine.url.database          # None for an in-memory database

    def verified():
        """The row as it is in the database file now (fresh connection), if its scores match the report."""
        if not db_file:
            return None
        row = score_store.read_result(db_file, user_id, candidate)
        return row if row and score_store.scores_match(row, (overall, avg)) else None

    try:
        record = InterviewResult.query.filter_by(user_id=user_id, candidate_name=candidate).first()
        if record is None:
            record = InterviewResult(user_id=user_id, candidate_name=candidate)
            db.session.add(record)
        record.language = language
        record.cv_score = overall            # CV Score = Overall score
        record.interview_score = avg         # Interview Score = Average per-question score
        record.feedback_reason = feedback
        db.session.commit()

        if not db_file:
            return record.id, "saved"
        row = verified()
        if row:
            print(f"[DB] Saved interview result (CV: {overall}, Interview: {avg}) for {candidate}")
            return row[0], "saved"
        problem = "the scores stored in the database do not match the report"
    except Exception as e:
        db.session.rollback()
        problem = str(e)
    print(f"[DB] Saving the scores failed ({problem}). Trying the fallback...")

    try:
        score_store.upsert_result(db_file, user_id, candidate, language, overall, avg, feedback)
        score_store.backfill(db_file, UPLOAD_FOLDER, names=[candidate])
        db.session.expire_all()
        row = verified()
        if row:
            print(f"[DB] Fallback saved the interview result for {candidate}")
            return row[0], "saved_via_fallback"
    except Exception as e:
        print(f"[DB Error] Fallback failed too: {e}")
    print(f"[DB Error] Could not store the scores for {candidate}. "
          f"They are in the report files; run: python backfill_scores.py")
    return None, "failed"


# ---- Grading runs in a background thread so the browser can show progress -------------------------
# One job per candidate folder, kept in memory (single-process server). A job is a dict:
#   state: "running" | "done" | "error"     done/total: questions graded so far / all questions
#   stage: "questions" | "summary"          durations: seconds each graded question took
#   step_started: monotonic time the current step began      report: the finished report
GRADING_JOBS = {}
GRADING_LOCK = threading.Lock()


def _run_grading_job(candidate, data, job):
    cand_dir = UPLOAD_FOLDER / candidate

    def on_progress(done, total, stage):
        now = time.monotonic()
        with GRADING_LOCK:
            job["total"] = total
            if stage == "questions" and done > job["done"]:
                job["durations"].append(now - job["step_started"])
                job["done"] = done
                job["step_started"] = now
            elif stage == "summary" and job["stage"] != "summary":
                job["stage"] = "summary"
                job["done"] = done
                job["step_started"] = now

    try:
        report = grade_interview.grade_interview(
            data=data,
            model=grade_interview.OLLAMA_MODEL,
            job_title=data.get("job_position") or "AI Engineer",
            job_requirements=None,
            progress=on_progress
        )
        report_path = cand_dir / f"{candidate}_answers_report.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        grade_interview.write_markdown_report(report, cand_dir / f"{candidate}_answers_report.md")
        with GRADING_LOCK:
            job["report"] = report
            job["state"] = "done"
    except Exception as e:
        print(f"[Grading Error] {candidate}: {e}")
        with GRADING_LOCK:
            job["state"] = "error"


def _start_grading_job(candidate, answers_path):
    """Starts grading in the background. Call with GRADING_LOCK held."""
    data = json.loads(answers_path.read_text(encoding="utf-8"))
    job = {
        "state": "running", "stage": "questions", "done": 0,
        "total": len(data.get("answers", [])),
        "durations": [], "step_started": time.monotonic(), "report": None,
    }
    GRADING_JOBS[candidate] = job
    threading.Thread(target=_run_grading_job, args=(candidate, data, job), daemon=True).start()
    return job


@app.route("/api/grading_status/<candidate>")
def api_grading_status(candidate):
    """Progress of the grading job, polled by static/js/grading.js."""
    with GRADING_LOCK:
        job = GRADING_JOBS.get(candidate)
        if job is None:
            return jsonify({"state": "missing"})
        total, done = job["total"], job["done"]
        eta = None
        if job["state"] == "running" and job["durations"]:
            # Average time per step so far, times the steps still to do (the questions left plus the
            # final summary), minus the time the current step has already been running.
            avg = sum(job["durations"]) / len(job["durations"])
            steps_left = (total + 1) - done
            eta = max(0.0, avg * steps_left - (time.monotonic() - job["step_started"]))
        response = jsonify({
            "state": job["state"], "stage": job["stage"],
            "done": done, "total": total, "eta": eta,
        })
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/report/<candidate>")
def report_page(candidate):
    cand_dir = UPLOAD_FOLDER / candidate
    answers_path = cand_dir / f"{candidate}_answers.json"

    if not answers_path.exists():
        abort(404)

    retry = request.args.get("retry") == "1"
    with GRADING_LOCK:
        job = GRADING_JOBS.get(candidate)
        if job is None or (retry and job["state"] == "error"):
            job = _start_grading_job(candidate, answers_path)
        finished = job["state"] == "done"
        if finished:
            GRADING_JOBS.pop(candidate, None)
            report = job["report"]

    if not finished:
        # Still grading (or failed): show the progress page, which polls /api/grading_status
        return render_template("grading.html", candidate=candidate)

    data = json.loads(answers_path.read_text(encoding="utf-8"))

    # Scores are saved only for a logged-in user.
    save_status = "not_logged_in"
    if current_user.is_authenticated:
        result_id, save_status = save_interview_scores(
            current_user.id, candidate, data.get("interview_language", "English"), report)

        # The applicant profile is saved separately, so a problem here can never lose the interview result.
        if result_id is not None:
            try:
                save_applicant_profile(current_user.id, result_id, cand_dir / f"{candidate}.json")
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"[DB Error] Could not save applicant profile: {e}")

    return render_template("report.html", report=report, save_status=save_status)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)