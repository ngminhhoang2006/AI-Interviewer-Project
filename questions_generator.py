import json
import os
from pathlib import Path
import ollama
import re
import unicodedata


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent


# ============================================================
# FIND JSON FILE
# ============================================================

def flatten_text(text: str) -> str:
    """
    Strips diacritics, converts Vietnamese đ/Đ, handles non-breaking spaces,
    and removes ALL non-alphanumeric characters for clean string comparison.
    """
    # Replace non-breaking spaces and Vietnamese Đ/đ
    text = text.replace("\u00a0", " ").replace("Đ", "D").replace("đ", "d")
    
    # Strip diacritics
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    
    # Keep only pure lowercase letters and numbers (removes spaces, hyphens, punctuation)
    return re.sub(r'[^a-z0-9]', '', stripped.casefold())


def find_json_file(applicant_name: str):
    """
    Find the applicant's JSON file by comparing flattened folder names.
    """
    applicant_name = applicant_name.strip().strip('"').strip("'")
    target_flat = flatten_text(applicant_name)

    # Search from script dir up to parent roots
    search_roots = [BASE_DIR, BASE_DIR.parent, BASE_DIR.parent.parent]

    matching_dirs = []
    for root in search_roots:
        if root.exists():
            for d in root.rglob("*"):
                if d.is_dir():
                    folder_flat = flatten_text(d.name)
                    # Check exact flattened match or containment
                    if folder_flat and (folder_flat == target_flat or target_flat in folder_flat):
                        matching_dirs.append(d)

    # Deduplicate matches
    matching_dirs = list(set(matching_dirs))

    if not matching_dirs:
        raise FileNotFoundError(
            f"\nCould not find a folder matching '{applicant_name}'.\n"
            f"Flattened search target: '{target_flat}'\n"
            f"Searched roots: {[str(r) for r in search_roots]}"
        )

    # Collect source JSON files inside matching folder(s)
    json_files = []
    for folder in matching_dirs:
        for file_path in folder.rglob("*.json"):
            # Exclude output question files
            if not file_path.name.casefold().endswith("_questions.json") and \
               not re.search(r'_questions_[a-z]+\.json$', file_path.name, re.IGNORECASE):
                json_files.append(file_path)

    if not json_files:
        raise FileNotFoundError(
            f"\nFound folder(s): {[d.name for d in matching_dirs]},\n"
            f"but no source CV JSON file was found inside."
        )

    if len(json_files) > 1:
        print("\nMultiple matching JSON files found:")
        for i, path in enumerate(json_files, start=1):
            print(f"{i}. {path}")

        while True:
            try:
                choice = int(input("\nSelect the file number: "))
                if 1 <= choice <= len(json_files):
                    return json_files[choice - 1]
                print("Invalid choice.")
            except ValueError:
                print("Please enter a number.")

    return json_files[0]


# ============================================================
# LOAD RESUME
# ============================================================

def load_resume(path):
    print(f"\nLoading: {path}")

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


# ============================================================
# GENERATE QUESTIONS
# ============================================================

def generate_questions(resume, language="English"):

    prompt = f"""
You are an experienced technical interviewer.

Your task is to analyze the candidate's CV and generate
high-quality interview questions specifically tailored to this candidate.

IMPORTANT LANGUAGE INSTRUCTION:
All generated questions and text MUST be written in {language}.
Keep JSON key names (like "question", "difficulty", "topic") in English,
but output their corresponding values in {language}.

Candidate CV:
{json.dumps(resume, indent=2, ensure_ascii=False)}

Generate questions in the following categories:
1. introduction
2. education
3. technical
4. projects
5. experience
6. certifications
7. behavioral
8. critical_thinking

For technical and project questions, include a difficulty: "easy", "medium", or "hard".
For categories where difficulty is not relevant, use "general".

Each question object must follow this structure:
{{
    "question": "...",
    "difficulty": "...",
    "topic": "..."
}}

IMPORTANT RULES:
- Questions must be relevant to the CV.
- Do not invent experience that isn't present in the CV.
- Prefer specific questions over generic questions.
- Include approximately 3-5 questions per category.
- Output MUST be valid JSON mapping category names to lists of question objects. Do not include introductory text, markdown formatting, or explanations.
"""

    print(f"\nGenerating interview questions in {language}...\n")

    response = ollama.chat(
        model="qwen3:8b",
        # Force structured JSON format natively from Ollama
        format="json", 
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are a professional technical interviewer "
                    f"who specializes in evaluating candidates. "
                    f"You must communicate in {language}. "
                    f"You must respond with valid JSON only."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    result = response["message"]["content"].strip()

    # Fallback cleanup using Regex to extract the pure JSON body
    json_match = re.search(r'(\{.*\}|\[.*\])', result, re.DOTALL)
    if json_match:
        result = json_match.group(0)

    try:
        return json.loads(result)
    except json.JSONDecodeError as e:
        print("\n--- Failed Raw Output from LLM ---")
        print(result)
        print("----------------------------------\n")
        raise e


# ============================================================
# SAVE QUESTIONS
# ============================================================

def save_questions(questions, output_path):

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(
            questions,
            file,
            indent=4,
            ensure_ascii=False
        )

    print(f"\nInterview questions saved to:")
    print(output_path)


# ============================================================
# MAIN
# ============================================================

def main():

    print("========================================")
    print("       AI Interview Question Generator")
    print("========================================")

    # Ask user for applicant name / folder name
    applicant_name = input("\nEnter applicant name: ")

    # Find the JSON inside the applicant's folder
    json_path = find_json_file(applicant_name)

    print(f"\nFound JSON file:")
    print(json_path)

    # Ask user for desired output language
    print("\nSelect question language:")
    print("1. English")
    print("2. Vietnamese (Tiếng Việt)")
    print("3. Custom")

    lang_choice = input("Enter choice (1-3) [default: 1]: ").strip()

    if lang_choice == "2":
        language = "Vietnamese"
    elif lang_choice == "3":
        language = input("Enter language name (e.g., Japanese, Spanish): ").strip() or "English"
    else:
        language = "English"

    # Load CV
    resume = load_resume(json_path)

    # Generate questions
    questions = generate_questions(resume, language=language)

    # Fetch candidate name and normalize non-breaking spaces (\u00a0) to regular spaces
    raw_name = resume.get("name", "candidate")
    clean_name = raw_name.replace("\u00a0", " ").strip()

    # Build output payload with the cleaned candidate name
    output = {
        "candidate": clean_name,
        "language": language,
        "source_file": json_path.name,
        "questions": questions
    }

    # Construct candidate-and-language-specific filename
    candidate_slug = (
        clean_name
        .lower()
        .replace(" ", "_")
    )
    lang_slug = language.lower()

    output_filename = f"{candidate_slug}_questions_{lang_slug}.json"
    output_path = json_path.parent / output_filename

    save_questions(output, output_path)

    print("\nDone!")


if __name__ == "__main__":
    main()