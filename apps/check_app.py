#!/usr/bin/env python3
import html
import re
import unicodedata
from pathlib import Path
from flask import Flask, render_template, request, jsonify
import sys
import sqlite3

# Add project root and system folder to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "system"))

try:
    import markdown
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False

try:
    import nh3  # HTML sanitizer
    HAS_SANITIZER = True
except ImportError:
    HAS_SANITIZER = False

app = Flask(
    __name__,
    template_folder=str(PROJECT_ROOT / "templates"),
    static_folder=str(PROJECT_ROOT / "static")
)

UPLOAD_FOLDER = PROJECT_ROOT / "uploads"
DB_PATH = PROJECT_ROOT / "database.db"


def flatten_text(text: str) -> str:
    """Normalizes text matching candidate folder names."""
    text = text.replace("\u00a0", " ").replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", stripped.casefold())


MAX_NAME_LEN = 100
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def validate_name(raw) -> str:
    """Validates a user-supplied candidate name. Raises ValueError with a safe message.

    This is input hygiene, NOT the SQL injection defence: quotes are allowed on purpose
    (names like O'Brien are legitimate). Injection is prevented by always passing user
    input to SQLite as bound parameters, never by building SQL strings.
    """
    if not isinstance(raw, str):
        raise ValueError("Candidate name must be text.")
    name = raw.strip()
    if not name:
        raise ValueError("Please enter a candidate name.")
    if len(name) > MAX_NAME_LEN:
        raise ValueError(f"Candidate name is too long (max {MAX_NAME_LEN} characters).")
    if _CONTROL_CHARS.search(name):
        raise ValueError("Candidate name contains invalid characters.")
    return name


def _open_readonly_db() -> sqlite3.Connection:
    """The checker only ever reads, so open the database read-only (least privilege)."""
    conn = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True, timeout=10)
    # Lets SQLite apply the same name normalisation as the rest of the app, inside the query.
    conn.create_function(
        "flatten", 1,
        lambda v: flatten_text(v) if isinstance(v, str) else "",
        deterministic=True,
    )
    return conn


def find_candidate_folders(name: str) -> list[Path]:
    """Finds candidate folders (directly inside the uploads folder) matching the search query."""
    target_flat = flatten_text(name)
    if not target_flat or not UPLOAD_FOLDER.exists():
        return []

    matches = []
    for d in UPLOAD_FOLDER.iterdir():
        if d.is_dir():
            folder_flat = flatten_text(d.name)
            if folder_flat and target_flat in folder_flat:
                matches.append(d)

    return sorted(matches, key=lambda x: str(x))


def find_report_files(folder: Path) -> list[Path]:
    """Finds grading report files within a candidate's folder."""
    return sorted(folder.rglob("*_answers_report.md"))


@app.route("/", methods=["GET"])
def index():
    return render_template("checker.html")

def get_candidate_scores(candidate_name: str):
    """Fetch scores from the SQLite interview_results table (name matched with text flattening).

    The name is passed as a bound parameter, so it is only ever treated as data.
    """
    empty = {"cv_score": "N/A", "interview_score": "N/A", "feedback": "", "date": ""}
    target_flat = flatten_text(candidate_name)
    if not target_flat or not DB_PATH.exists():
        return empty

    conn = _open_readonly_db()
    try:
        row = conn.execute(
            "SELECT candidate_name, cv_score, interview_score, feedback_reason, created_at "
            "FROM interview_results "
            "WHERE flatten(candidate_name) != '' "
            "  AND (instr(flatten(candidate_name), :target) > 0 "
            "       OR instr(:target, flatten(candidate_name)) > 0) "
            "ORDER BY id LIMIT 1",
            {"target": target_flat},
        ).fetchone()
    except sqlite3.Error as e:
        print(f"Database error while reading scores: {e}")
        return empty
    finally:
        conn.close()

    if row is None:
        return empty

    # SWAPPED: Overall score (row[2]) is now CV Score, Average per-q (row[1]) is Interview Score
    return {
        "cv_score": str(row[2]) if row[2] is not None else "N/A",
        "interview_score": str(row[1]) if row[1] is not None else "N/A",
        "feedback": row[3] or "",
        "date": str(row[4]) if row[4] else "",
    }


def extract_scores_from_md(report_path: Path):
    if not report_path.exists():
        return "N/A", "N/A"
    
    try:
        content = report_path.read_text(encoding="utf-8")
        
        # Matches numbers before optional /10 even inside markdown bolding (**Overall score: 7/10**)
        overall_match = re.search(r"Overall\s+score:\s*\*?\*?\s*([\d.]+)", content, re.IGNORECASE)
        avg_match = re.search(r"Average\s+per-question\s+score:\s*\*?\*?\s*([\d.]+)", content, re.IGNORECASE)
        
        # Mapping per requirement:
        cv_score = overall_match.group(1) if overall_match else "N/A"
        interview_score = avg_match.group(1) if avg_match else "N/A"
        
        return cv_score, interview_score
    except Exception as e:
        print(f"Error reading report {report_path}: {e}")
        return "N/A", "N/A"


@app.route("/api/search", methods=["POST"])
def search_candidate():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid request."}), 400
    try:
        query = validate_name(data.get("name", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    folders = find_candidate_folders(query)
    if not folders:
        return jsonify({"candidates": [], "message": f"No candidate matching '{query}' found."})

    results = []
    for f in folders:
        reports = find_report_files(f)
        
        cv_score = "N/A"
        interview_score = "N/A"
        
        # 1. First attempt: Extract directly from the Markdown report file on disk
        if reports:
            cv_score, interview_score = extract_scores_from_md(reports[0])
            
        # 2. Fallback attempt: Query SQLite DB if report was missing or scores couldn't be parsed
        if cv_score == "N/A" or interview_score == "N/A":
            db_scores = get_candidate_scores(query)
            if db_scores["cv_score"] == "N/A" and db_scores["interview_score"] == "N/A":
                db_scores = get_candidate_scores(f.name)
            
            if cv_score == "N/A":
                # In DB: interview_score holds 7.0 (Overall), cv_score holds 6.6 (Avg)
                cv_score = db_scores["interview_score"]
            if interview_score == "N/A":
                interview_score = db_scores["cv_score"]

        results.append({
            "folder_name": f.name,
            "folder_path": str(f.relative_to(PROJECT_ROOT)),
            "reports": [r.name for r in reports],
            "cv_score": cv_score,
            "interview_score": interview_score
        })

    return jsonify({"candidates": results})


@app.route("/api/get_report", methods=["POST"])
def get_report():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid request."}), 400
    relative_folder = str(data.get("folder_path", ""))
    report_filename = str(data.get("report_filename", ""))

    folder_path = (PROJECT_ROOT / relative_folder).resolve()
    report_path = (folder_path / report_filename).resolve()

    # Only report files inside the uploads folder can be opened (also blocks "../" tricks)
    if (UPLOAD_FOLDER.resolve() not in report_path.parents
            or not report_path.name.endswith("_answers_report.md")):
        return jsonify({"error": "Access denied"}), 403

    if not report_path.exists():
        return jsonify({"error": "Report file not found."}), 404

    md_content = report_path.read_text(encoding="utf-8")

    # The report text is written by an LLM from the candidate's CV and answers, so it is
    # untrusted. Markdown lets raw HTML through (<script>, <img onerror=...>), so the rendered
    # HTML MUST be sanitized before the browser inserts it into the page. If either package is
    # missing we fall back to escaped plain text instead of risking unsanitized HTML.
    if HAS_MARKDOWN and HAS_SANITIZER:
        html_content = nh3.clean(
            markdown.markdown(md_content, extensions=['tables', 'fenced_code'])
        )
    else:
        # Fallback raw pre-formatted text
        html_content = f"<pre>{html.escape(md_content)}</pre>"

    return jsonify({
        "candidate": folder_path.name,
        "filename": report_filename,
        "content_html": html_content,
        "content_raw": md_content
    })


if __name__ == "__main__":
    import os
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", host=os.environ.get("HOST", "127.0.0.1"), port=5001)