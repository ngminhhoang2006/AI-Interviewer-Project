#!/usr/bin/env python3
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


def find_candidate_folders(name: str) -> list[Path]:
    """Finds folders matching candidate search query across PROJECT_ROOT and uploads."""
    target_flat = flatten_text(name)
    search_roots = [PROJECT_ROOT, UPLOAD_FOLDER]
    matches = []

    for root in search_roots:
        if root.exists():
            for d in root.rglob("*"):
                if d.is_dir():
                    folder_flat = flatten_text(d.name)
                    if folder_flat and (target_flat == folder_flat or target_flat in folder_flat):
                        matches.append(d)

    # Return unique paths
    return sorted(list(set(matches)), key=lambda x: str(x))


def find_report_files(folder: Path) -> list[Path]:
    """Finds grading report files within a candidate's folder."""
    return sorted(folder.rglob("*_answers_report.md"))


@app.route("/", methods=["GET"])
def index():
    return render_template("checker.html")

def get_candidate_scores(candidate_name: str):
    """Fetch scores directly from SQLite interview_results table with text flattening."""
    if not DB_PATH.exists():
        return {"cv_score": "N/A", "interview_score": "N/A", "feedback": "", "date": ""}

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT candidate_name, cv_score, interview_score, feedback_reason, created_at FROM interview_results"
        )
        rows = cursor.fetchall()
    finally:
        conn.close()
    
    target_flat = flatten_text(candidate_name)
    
    for row in rows:
        db_cand_name = row[0]
        if target_flat and (target_flat in flatten_text(db_cand_name) or flatten_text(db_cand_name) in target_flat):
            # SWAPPED: Overall score (row[2]) is now CV Score, Average per-q (row[1]) is Interview Score
            return {
                "cv_score": str(row[2]) if row[2] is not None else "N/A",
                "interview_score": str(row[1]) if row[1] is not None else "N/A",
                "feedback": row[3] or "",
                "date": str(row[4]) if row[4] else ""
            }
            
    return {"cv_score": "N/A", "interview_score": "N/A", "feedback": "", "date": ""}


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
    data = request.json or {}
    query = data.get("name", "").strip()

    if not query:
        return jsonify({"error": "Please enter a candidate name."}), 400

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
    data = request.json or {}
    relative_folder = data.get("folder_path", "")
    report_filename = data.get("report_filename", "")

    folder_path = (PROJECT_ROOT / relative_folder).resolve()

    # Security check to avoid directory traversal
    if not str(folder_path).startswith(str(PROJECT_ROOT)):
        return jsonify({"error": "Access denied"}), 403

    report_path = folder_path / report_filename
    if not report_path.exists():
        return jsonify({"error": "Report file not found."}), 404

    md_content = report_path.read_text(encoding="utf-8")

    # Render Markdown to HTML if markdown package is installed
    if HAS_MARKDOWN:
        html_content = markdown.markdown(md_content, extensions=['tables', 'fenced_code'])
    else:
        # Fallback raw pre-formatted text
        html_content = f"<pre>{md_content}</pre>"

    return jsonify({
        "candidate": folder_path.name,
        "filename": report_filename,
        "content_html": html_content,
        "content_raw": md_content
    })


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)