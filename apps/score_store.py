"""Reads and writes interview scores directly in the SQLite database (standard library only).

Used by the website (apps/interview_app.py) to double-check and, if needed, repair a save, and by
backfill_scores.py. The scores come from the report the grader writes to disk
(uploads/<name>/<name>_answers_report.json, or the .md next to it).
"""
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

PLACEHOLDER = "Completed interview evaluation."


def to_float(value):
    """8, 8.0, "8", "8/10" -> float; anything else -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.search(r"\d+(?:\.\d+)?", value)
        return float(m.group()) if m else None
    return None


def scores_from_disk(uploads, name):
    """(overall, average, summary) from the saved report of this candidate, or None if no report exists."""
    folder = Path(uploads) / name
    jpath = folder / f"{name}_answers_report.json"
    mpath = folder / f"{name}_answers_report.md"
    if jpath.exists():
        try:
            rep = json.loads(jpath.read_text(encoding="utf-8"))
            overall = rep.get("overall") if isinstance(rep.get("overall"), dict) else {}
            return (to_float(overall.get("overall_score", rep.get("overall_score"))),
                    to_float(rep.get("average_score")),
                    overall.get("summary") or None)
        except (OSError, ValueError):
            pass
    if mpath.exists():
        text = mpath.read_text(encoding="utf-8")
        o = re.search(r"\*\*Overall score:\*\*\s*([\d.]+)", text)
        a = re.search(r"\*\*Average per-question score:\*\*\s*([\d.]+)", text)
        return (to_float(o.group(1)) if o else None, to_float(a.group(1)) if a else None, None)
    return None


def _connect(db_file):
    return sqlite3.connect(str(db_file), timeout=10)


def read_result(db_file, user_id, name):
    """(id, cv_score, interview_score) as stored in the database file right now, or None."""
    con = _connect(db_file)
    try:
        return con.execute(
            "SELECT id, cv_score, interview_score FROM interview_results "
            "WHERE user_id = ? AND candidate_name = ? ORDER BY id LIMIT 1", (user_id, name)).fetchone()
    finally:
        con.close()


def scores_match(row, expected):
    """row = (id, cv, interview) from read_result; expected = (overall, average) from the report.
    A score the report doesn't have (None) can't be checked, so it always matches."""
    for stored, wanted in zip(row[1:], expected):
        if wanted is None:
            continue
        if stored is None or abs(float(stored) - float(wanted)) > 1e-6:
            return False
    return True


def upsert_result(db_file, user_id, name, language, overall, average, feedback):
    """Direct SQLite write that does not depend on the SQLAlchemy session."""
    con = _connect(db_file)
    try:
        with con:
            cur = con.execute(
                "UPDATE interview_results SET language = ?, cv_score = ?, interview_score = ?, "
                "feedback_reason = ? WHERE user_id = ? AND candidate_name = ?",
                (language, overall, average, str(feedback), user_id, name))
            if cur.rowcount == 0:
                con.execute(
                    "INSERT INTO interview_results (user_id, candidate_name, language, cv_score, "
                    "interview_score, feedback_reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, name, language, overall, average, str(feedback),
                     datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")))
    finally:
        con.close()


def backfill(db_file, uploads, names=None, dry_run=False, before_write=None, log=print):
    """Fills empty scores (and the placeholder feedback) from the report files on disk.
    Never overwrites a score that is already there. Returns the list of changes made/planned."""
    sql = ("SELECT id, candidate_name, cv_score, interview_score, feedback_reason FROM interview_results "
           "WHERE (cv_score IS NULL OR interview_score IS NULL OR feedback_reason IS NULL OR feedback_reason = ?)")
    params = [PLACEHOLDER]
    if names:
        sql += " AND candidate_name IN (%s)" % ",".join("?" * len(names))
        params += list(names)

    con = _connect(db_file)
    changes = []
    try:
        for rid, name, cv, iv, fb in con.execute(sql, params).fetchall():
            found = scores_from_disk(uploads, name)
            if not found:
                log(f"  [skip] #{rid} {name}: no report file found in {Path(uploads) / name}")
                continue
            overall, avg, summary = found
            new_cv = overall if cv is None and overall is not None else cv
            new_iv = avg if iv is None and avg is not None else iv
            new_fb = summary if (not fb or fb == PLACEHOLDER) and summary else fb
            if (new_cv, new_iv, new_fb) == (cv, iv, fb):
                log(f"  [skip] #{rid} {name}: the report has no scores to fill in")
                continue
            log(f"  [fix]  #{rid} {name}: CV/overall {cv} -> {new_cv} | interview/average {iv} -> {new_iv}"
                + (" | feedback updated" if new_fb != fb else ""))
            changes.append((rid, name, new_cv, new_iv, new_fb))

        if changes and not dry_run:
            if before_write:
                before_write()
            with con:
                con.executemany(
                    "UPDATE interview_results SET cv_score = ?, interview_score = ?, feedback_reason = ? WHERE id = ?",
                    [(cv, iv, fb, rid) for rid, _n, cv, iv, fb in changes])
    finally:
        con.close()
    return changes
