#!/usr/bin/env python3
"""
ai_interview_system.py

Runs the full AI interview pipeline end-to-end in one process:

    1. cv_reader          -> parse a CV PDF into structured JSON
    2. questions_generator -> generate interview questions from that JSON
    3. chatbot             -> conduct the interview and record answers
    4. grade_interview     -> grade the answers and produce a report

Rather than re-implementing any logic, this script imports the four
existing modules and calls their functions directly, passing the
outputs of one stage straight into the next. This avoids re-searching
the filesystem or re-typing the candidate's name/language at every
step, since the orchestrator already knows the paths and values from
the previous stage.

Place this file in the same folder as cv_reader.py, questions_generator.py,
chatbot.py, and grade_interview.py, then run:

    python ai_interview_system.py.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------
# Import the four existing scripts as modules (their `main()` guards
# mean nothing runs automatically on import -- we just get access to
# their functions).
# --------------------------------------------------------------------
import cv_reader
import questions_generator
import chatbot
import grade_interview


SCRIPT_DIR = Path(__file__).resolve().parent


def banner(text: str) -> None:
    print("\n" + "=" * 60)
    print(text)
    print("=" * 60)


# ======================================================================
# STAGE 1: CV -> structured JSON
# ======================================================================

def stage_cv_reader(pdf_name: str | None) -> tuple[Path, dict]:
    banner("STEP 1/4 — Reading CV")

    if not pdf_name:
        pdf_name = input("Enter the CV filename / Nhập tên file CV: ").strip()

    if not pdf_name.lower().endswith(".pdf"):
        pdf_name += ".pdf"

    pdf_path = cv_reader.find_pdf(pdf_name)

    if pdf_path is None:
        print(f"Could not find '{pdf_name}' / Không tìm thấy file '{pdf_name}'.")
        sys.exit(1)

    print(f"Found PDF: {pdf_path}")

    text = cv_reader.extract_text(pdf_path)
    applicant = cv_reader.extract_applicant_info(text)

    raw_name = applicant.get("name") or "Unknown_Applicant"
    safe_name = re.sub(r'[\\/*?:"<>|]', "", raw_name).strip()

    output_dir = pdf_path.parent / safe_name
    output_dir.mkdir(parents=True, exist_ok=True)

    cv_json_path = output_dir / f"{safe_name}.json"

    with open(cv_json_path, "w", encoding="utf-8") as f:
        json.dump(applicant, f, indent=4, ensure_ascii=False)

    print(f"CV parsed successfully. JSON saved to:\n  {cv_json_path}")

    return cv_json_path, applicant


# ======================================================================
# STAGE 2: CV JSON -> interview questions JSON
# ======================================================================

def stage_questions_generator(
    cv_json_path: Path, resume: dict, language_choice: str | None
) -> tuple[Path, str, str]:
    banner("STEP 2/4 — Generating Interview Questions")

    if language_choice is None:
        print("Select question language:")
        print("1. English")
        print("2. Vietnamese (Tiếng Việt)")
        print("3. Custom")
        language_choice = input("Enter choice (1-3) [default: 1]: ").strip()

    if language_choice == "2":
        language = "Vietnamese"
    elif language_choice == "3":
        language = input("Enter language name (e.g., Japanese, Spanish): ").strip() or "English"
    elif language_choice in ("", "1"):
        language = "English"
    else:
        # Allow a language name to be passed directly via --language
        language = language_choice

    questions = questions_generator.generate_questions(resume, language=language)

    raw_name = resume.get("name", "candidate")
    clean_name = raw_name.replace("\u00a0", " ").strip()

    output = {
        "candidate": clean_name,
        "language": language,
        "source_file": cv_json_path.name,
        "questions": questions,
    }

    candidate_slug = clean_name.lower().replace(" ", "_")
    lang_slug = language.lower()
    output_filename = f"{candidate_slug}_questions_{lang_slug}.json"
    questions_path = cv_json_path.parent / output_filename

    questions_generator.save_questions(output, questions_path)

    return questions_path, clean_name, language


# ======================================================================
# STAGE 3: questions JSON -> answers JSON (the interview itself)
# ======================================================================

def stage_chatbot(questions_path: Path, candidate_name: str, language: str) -> Path:
    banner("STEP 3/4 — Conducting Interview")

    questions_data = chatbot.load_questions(questions_path)
    all_questions = chatbot.extract_questions(questions_data)

    if not all_questions:
        print("ERROR: No questions found in the generated JSON file.")
        sys.exit(1)

    print(f"Loaded {len(all_questions)} questions.")
    print(f"Interview language: {language}")
    print("Type 'quit' at any answer prompt to stop early.\n")

    answers = chatbot.run_interview(candidate_name, language, all_questions)

    answers_path = chatbot.save_answers(candidate_name, answers, questions_path, language)

    return answers_path


# ======================================================================
# STAGE 4: answers JSON -> grading report (JSON + Markdown)
# ======================================================================

def stage_grade_interview(
    answers_path: Path,
    model: str,
    job_title: str,
    job_requirements_arg: str | None,
) -> None:
    banner("STEP 4/4 — Grading Interview")

    job_requirements = None
    if job_requirements_arg:
        req_path = Path(job_requirements_arg)
        job_requirements = (
            req_path.read_text(encoding="utf-8")
            if req_path.exists()
            else job_requirements_arg
        )

    data = json.loads(answers_path.read_text(encoding="utf-8"))

    report = grade_interview.grade_interview(data, model, job_title, job_requirements)

    out_json = answers_path.parent / f"{answers_path.stem}_report.json"
    out_md = answers_path.parent / f"{answers_path.stem}_report.md"

    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    grade_interview.write_markdown_report(report, out_md)

    print("\n=== DONE ===")
    print(f"Average score: {report['average_score']}/10")
    print(
        f"Overall: {report['overall'].get('recommendation')} "
        f"({report['overall'].get('overall_score')}/10)"
    )
    print(f"JSON report: {out_json}")
    print(f"Markdown report: {out_md}")


# ======================================================================
# MAIN
# ======================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the full CV -> questions -> interview -> grading pipeline in one go."
    )
    parser.add_argument("--pdf", help="CV filename to search for (skips the prompt).")
    parser.add_argument(
        "--language",
        help="Question/interview language: '1' (English), '2' (Vietnamese), "
        "or any language name (e.g. 'Japanese'). Skips the language menu.",
    )
    parser.add_argument(
        "--model",
        default=grade_interview.OLLAMA_MODEL,
        help=f"Ollama model to use for grading (default: {grade_interview.OLLAMA_MODEL}).",
    )
    parser.add_argument(
        "--job-title", default="AI Engineer", help="Job title the candidate is interviewing for."
    )
    parser.add_argument(
        "--job-requirements",
        default=None,
        help="Path to a requirements text file, or the requirements text itself.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    banner("AI INTERVIEW PIPELINE")
    print("This will run: CV parsing -> question generation -> interview -> grading.\n")

    cv_json_path, applicant = stage_cv_reader(args.pdf)
    questions_path, candidate_name, language = stage_questions_generator(
        cv_json_path, applicant, args.language
    )
    answers_path = stage_chatbot(questions_path, candidate_name, language)
    stage_grade_interview(answers_path, args.model, args.job_title, args.job_requirements)


if __name__ == "__main__":
    main()