#!/usr/bin/env python3
"""
grade_interview.py

Grades a candidate's interview answers using a local Ollama LLM (qwen3:8b)
and produces a per-question score + comment plus an overall hiring recommendation.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
import unicodedata

import requests

OLLAMA_MODEL = "qwen3:8b"
SCRIPT_DIR = Path(__file__).resolve().parent


def call_ollama(model: str, system: str, user: str, retries: int = 3) -> str:
    """Send a chat request to a local Ollama server and return the text reply."""
    url = "http://localhost:11434/api/chat"
    payload = {
        "model": model,
        "format": "json",  # Force native JSON output from Ollama
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"  [warn] Ollama call failed (attempt {attempt}/{retries}): {e}", file=sys.stderr)
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"Ollama call failed after {retries} attempts: {last_err}")


def extract_json_block(text: str) -> dict:
    """Parse the JSON object from model output.

    Since we request `"format": "json"` from Ollama, `text` should already be
    a clean JSON string in the common case -- try that first. Only fall back
    to regex extraction (stripping <think> blocks and non-breaking spaces)
    if the direct parse fails, and use a GREEDY match (`\\{.*\\}`) so nested
    JSON objects aren't truncated at the first closing brace.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = cleaned.replace("\u00a0", " ").strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Greedy match: grabs from the first "{" to the LAST "}", so nested
    # objects/arrays inside fields (e.g. inside "comment") aren't cut off.
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in model output:\n{text}")
    return json.loads(match.group(0))


PER_QUESTION_SYSTEM = """You are a strict, fair technical interviewer grading a job candidate's
answers for a hiring decision. You evaluate relevance, technical depth, clarity,
and honesty (watch for vague buzzword-only answers with no real substance).
Output valid JSON only matching:
{"score": <integer 1-10>, "strengths": "<short phrase>", "concerns": "<short phrase>", "comment": "<1-3 sentence evaluation>"}
"""

OVERALL_SYSTEM = """You are a hiring manager synthesizing an interview evaluation for a candidate.
You are given the job title, optional job requirements, and a list of per-question
scores/comments. Produce a final hiring judgement.
Output valid JSON only matching:
{"overall_score": <integer 1-10>, "recommendation": "<Strong Hire|Hire|Borderline|No Hire>", "summary": "<3-6 sentence summary of fit, strengths, and gaps>"}
"""


def grade_answer(model: str, job_title: str, q: dict) -> dict:
    user_prompt = (
        f"Job title being interviewed for: {job_title}\n"
        f"Question topic: {q.get('topic')}\n"
        f"Question difficulty: {q.get('difficulty')}\n"
        f"Question: {q['question']}\n"
        f"Candidate answer: {q['answer']}\n\n"
        "Grade this answer now."
    )
    raw = call_ollama(model, PER_QUESTION_SYSTEM, user_prompt)
    try:
        parsed = extract_json_block(raw)
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] Could not parse grading JSON for Q{q.get('question_number', '?')}: {e}", file=sys.stderr)
        parsed = {"score": None, "strengths": "", "concerns": "", "comment": raw.strip()}
    return parsed


def grade_interview(data: dict, model: str, job_title: str, job_requirements: str | None) -> dict:
    raw_candidate = data.get("candidate", "Unknown candidate")
    candidate = raw_candidate.replace("\u00a0", " ").strip()
    answers = data.get("answers", [])

    print(f"Grading {len(answers)} answers for {candidate} using model '{model}'...")

    results = []
    for idx, q in enumerate(answers, start=1):
        q_num = q.get("question_number", idx)
        print(f"  -> Q{q_num}: {q.get('question', '')[:60]}...")
        grade = grade_answer(model, job_title, q)
        results.append({
            "question_number": q_num,
            "topic": q.get("topic"),
            "difficulty": q.get("difficulty"),
            "question": q.get("question"),
            "answer": q.get("answer"),
            **grade,
        })

    # Synthesize results
    summary_lines = []
    for r in results:
        summary_lines.append(
            f"Q{r['question_number']} [{r.get('topic')}/{r.get('difficulty')}] "
            f"score={r.get('score')} | strengths={r.get('strengths')} | "
            f"concerns={r.get('concerns')} | comment={r.get('comment')}"
        )
    overall_user_prompt = (
        f"Candidate: {candidate}\n"
        f"Job title: {job_title}\n"
        f"Job requirements: {job_requirements or 'Not specified'}\n\n"
        "Per-question evaluations:\n" + "\n".join(summary_lines) + "\n\n"
        "Now produce the final overall hiring judgement."
    )
    raw_overall = call_ollama(model, OVERALL_SYSTEM, overall_user_prompt)
    try:
        overall = extract_json_block(raw_overall)
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] Could not parse overall JSON: {e}", file=sys.stderr)
        overall = {"overall_score": None, "recommendation": "Unknown", "summary": raw_overall.strip()}

    valid_scores = [r["score"] for r in results if isinstance(r.get("score"), (int, float))]
    avg_score = round(sum(valid_scores) / len(valid_scores), 2) if valid_scores else None

    return {
        "candidate": candidate,
        "job_title": job_title,
        "model_used": model,
        "average_score": avg_score,
        "overall": overall,
        "per_question": results,
    }


def write_markdown_report(report: dict, path: Path) -> None:
    lines = []
    lines.append(f"# Interview Evaluation — {report['candidate']}")
    lines.append("")
    lines.append(f"**Job title:** {report['job_title']}  ")
    lines.append(f"**Model used:** {report['model_used']}  ")
    lines.append(f"**Average per-question score:** {report['average_score']}/10  ")
    overall = report["overall"]
    lines.append(f"**Overall score:** {overall.get('overall_score')}/10  ")
    lines.append(f"**Recommendation:** {overall.get('recommendation')}  ")
    lines.append("")
    lines.append("## Summary")
    lines.append(overall.get("summary", ""))
    lines.append("")
    lines.append("## Per-question breakdown")
    for r in report["per_question"]:
        lines.append(f"### Q{r['question_number']} ({r.get('topic')}, {r.get('difficulty')}) — Score: {r.get('score')}/10")
        lines.append(f"- **Question:** {r['question']}")
        lines.append(f"- **Answer:** {r['answer']}")
        lines.append(f"- **Strengths:** {r.get('strengths')}")
        lines.append(f"- **Concerns:** {r.get('concerns')}")
        lines.append(f"- **Comment:** {r.get('comment')}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")

def flatten_text(text: str) -> str:
    """
    Strips diacritics, converts Vietnamese đ/Đ, handles non-breaking spaces,
    and removes ALL non-alphanumeric characters for clean string comparison.
    """
    text = text.replace("\u00a0", " ").replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    return re.sub(r'[^a-z0-9]', '', stripped.casefold())


def find_default_input_json() -> Path:
    """
    Interactively prompts for candidate name or auto-detects an applicant's
    _answers.json file located inside their folder across project roots.
    """
    applicant_name = input("Enter candidate / folder name (e.g. Nguyễn Minh Hoàng): ").strip()
    target_flat = flatten_text(applicant_name)

    search_roots = [SCRIPT_DIR, SCRIPT_DIR.parent, SCRIPT_DIR.parent.parent]

    # 1. Match applicant directories
    matching_dirs = []
    for root in search_roots:
        if root.exists():
            for d in root.rglob("*"):
                if d.is_dir():
                    folder_flat = flatten_text(d.name)
                    if folder_flat and (folder_flat == target_flat or target_flat in folder_flat):
                        matching_dirs.append(d)

    matching_dirs = list(set(matching_dirs))

    # 2. Collect answer JSON files
    candidates = []
    for folder in matching_dirs:
        for p in folder.rglob("*.json"):
            # Ensure it's an answer file and not an output report
            if "answers" in flatten_text(p.name) and not p.name.lower().startswith("report"):
                candidates.append(p)

    # Fallback: search globally if folder matching fails
    if not candidates:
        for root in search_roots:
            if root.exists():
                for p in root.rglob("*_answers.json"):
                    if target_flat in flatten_text(p.name) or target_flat in flatten_text(p.parent.name):
                        candidates.append(p)

    candidates = list(set(candidates))

    if not candidates:
        raise FileNotFoundError(
            f"Could not find an answers JSON file for '{applicant_name}'.\n"
            f"Searched target: '{target_flat}' inside roots: {[str(r) for r in search_roots]}"
        )

    if len(candidates) == 1:
        return candidates[0]

    return prompt_for_json_choice(candidates, SCRIPT_DIR)


def prompt_for_json_choice(candidates: list[Path], script_dir: Path) -> Path:
    """Ask the user (via stdin) which of several JSON files to grade."""
    print(f"Multiple .json files found in {script_dir}:")
    for i, p in enumerate(candidates, start=1):
        print(f"  [{i}] {p.name}")

    while True:
        choice = input("Enter the number or exact filename of the file to grade: ").strip()
        if not choice:
            continue
        # Allow selecting by list index
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(candidates):
                return candidates[idx - 1]
            print(f"  [!] Please enter a number between 1 and {len(candidates)}.")
            continue
        # Allow selecting by filename (with or without .json suffix)
        name = choice if choice.lower().endswith(".json") else f"{choice}.json"
        matches = [p for p in candidates if p.name == name]
        if matches:
            return matches[0]
        print(f"  [!] '{choice}' doesn't match any listed file. Try again.")


def main():
    parser = argparse.ArgumentParser(description="Grade candidate interview answers using Ollama.")
    parser.add_argument(
        "input_json",
        type=Path,
        nargs="?",
        default=None,
        help="Path to interview answers JSON file.",
    )
    parser.add_argument("--model", default=OLLAMA_MODEL, help=f"Ollama model name (default: {OLLAMA_MODEL})")
    parser.add_argument("--job-title", default="AI Engineer", help="Job title candidate is interviewing for")
    parser.add_argument("--job-requirements", default=None, help="Path to requirements text file or raw text string")
    parser.add_argument("--out", type=Path, default=None, help="Output JSON report path")
    parser.add_argument("--out-md", type=Path, default=None, help="Output Markdown report path")
    args = parser.parse_args()

    if args.input_json is None:
        try:
            args.input_json = find_default_input_json()
            print(f"[info] Using: {args.input_json}")
        except FileNotFoundError as e:
            parser.error(str(e))

    if not args.input_json.exists():
        parser.error(f"input_json path does not exist: {args.input_json}")

    # Set report paths inside the applicant's directory if not explicitly overridden
    out_json = args.out if args.out else args.input_json.parent / f"{args.input_json.stem}_report.json"
    out_md = args.out_md if args.out_md else args.input_json.parent / f"{args.input_json.stem}_report.md"

    content = args.input_json.read_text(encoding="utf-8")
    data = json.loads(content)

    job_requirements = None
    if args.job_requirements:
        req_path = Path(args.job_requirements)
        job_requirements = req_path.read_text(encoding="utf-8") if req_path.exists() else args.job_requirements

    report = grade_interview(data, args.model, args.job_title, job_requirements)

    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown_report(report, out_md)

    print("\n=== DONE ===")
    print(f"Average score: {report['average_score']}/10")
    print(f"Overall: {report['overall'].get('recommendation')} ({report['overall'].get('overall_score')}/10)")
    print(f"JSON report: {out_json}")
    print(f"Markdown report: {out_md}")


if __name__ == "__main__":
    main()