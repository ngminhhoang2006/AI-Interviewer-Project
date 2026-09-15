#!/usr/bin/env python3
import re
import unicodedata
from pathlib import Path
from flask import Flask, render_template, request, jsonify
import sys

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
        results.append({
            "folder_name": f.name,
            "folder_path": str(f.relative_to(PROJECT_ROOT)),
            "reports": [r.name for r in reports]
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