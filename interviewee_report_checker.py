#!/usr/bin/env python3
"""
interviewee_report_checker.py

Prompts for an interviewee's name, locates their folder (matching by
name the same way the rest of the pipeline does -- ignoring case,
diacritics, and spacing), and prints the contents of their grading
report:

    <flattened_candidate_name>_answers_report.md

Place this alongside the other pipeline scripts / candidate folders
and run:

    python interviewee_report_checker.py
"""

import re
import sys
import unicodedata
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def flatten_text(text: str) -> str:
    """
    Strips diacritics, converts Vietnamese đ/Đ, handles non-breaking spaces,
    and removes ALL non-alphanumeric characters for clean string comparison.
    (Same normalization used across the interview pipeline scripts, so a
    folder like "Nguyen Minh Hoang" matches input like "nguyễn minh hoàng".)
    """
    text = text.replace("\u00a0", " ").replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", stripped.casefold())


def find_candidate_folders(name: str, search_roots) -> list[Path]:
    """Find folders whose (flattened) name matches or contains the target."""
    target_flat = flatten_text(name)

    matches = []
    for root in search_roots:
        if root.exists():
            for d in root.rglob("*"):
                if d.is_dir():
                    folder_flat = flatten_text(d.name)
                    if folder_flat and (folder_flat == target_flat or target_flat in folder_flat):
                        matches.append(d)

    return list(set(matches))


def find_report_files(folder: Path) -> list[Path]:
    """Find any interview grading report(s) inside a candidate's folder."""
    return sorted(folder.rglob("*_answers_report.md"))


def prompt_choice(items: list, label: str):
    print(f"\nMultiple {label} found:")
    for i, item in enumerate(items, start=1):
        print(f"  [{i}] {item}")

    while True:
        choice = input("Enter the number to select: ").strip()
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(items):
                return items[idx - 1]
        print("Invalid choice, please enter a valid number.")


def main():
    interviewee_name = input("Enter interviewee name: ").strip()

    if not interviewee_name:
        print("No name entered.")
        sys.exit(1)

    # Only search inside the script's own folder (not parent directories),
    # so it doesn't pick up unrelated matches from sibling project folders.
    folders = find_candidate_folders(interviewee_name, [SCRIPT_DIR])

    if not folders:
        print(f"Could not find a folder matching '{interviewee_name}'.")
        sys.exit(1)

    folder = folders[0] if len(folders) == 1 else prompt_choice(folders, "matching folders")

    report_files = find_report_files(folder)

    if not report_files:
        print(f"No report file found inside '{folder}'.")
        print(f"Expected something like: {flatten_text(interviewee_name)}_answers_report.md")
        sys.exit(1)

    report_file = report_files[0] if len(report_files) == 1 else prompt_choice(report_files, "report files")

    print(f"\nReading report: {report_file}\n")
    print("=" * 60)
    print(report_file.read_text(encoding="utf-8"))
    print("=" * 60)


if __name__ == "__main__":
    main()