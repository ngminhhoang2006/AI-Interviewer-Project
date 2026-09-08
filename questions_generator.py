import json
import os
from pathlib import Path
import ollama


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent


# ============================================================
# FIND JSON FILE
# ============================================================

def find_json_file(filename):
    """
    Search recursively for the requested JSON file
    starting from the directory containing this script.
    """

    # Remove accidental quotes/spaces
    filename = filename.strip().strip('"').strip("'")

    # Add .json if the user didn't type it
    if not filename.lower().endswith(".json"):
        filename += ".json"

    # Search recursively
    matches = list(BASE_DIR.rglob(filename))

    if not matches:
        raise FileNotFoundError(
            f"\nCould not find '{filename}'.\n"
            f"Search directory: {BASE_DIR}"
        )

    if len(matches) > 1:
        print("\nMultiple files with that name were found:")

        for i, path in enumerate(matches, start=1):
            print(f"{i}. {path}")

        while True:
            try:
                choice = int(input("\nSelect the file number: "))

                if 1 <= choice <= len(matches):
                    return matches[choice - 1]

                print("Invalid choice.")

            except ValueError:
                print("Please enter a number.")

    return matches[0]


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

def generate_questions(resume):

    prompt = f"""
You are an experienced technical interviewer.

Your task is to analyze the candidate's CV and generate
high-quality interview questions specifically tailored
to this candidate.

Candidate CV:

{json.dumps(resume, indent=2, ensure_ascii=False)}

Generate questions in the following categories:

1. introduction
   - General questions about the candidate
   - Their background and career goals

2. education
   - Questions about their degree
   - Relevant coursework
   - Academic knowledge

3. technical
   - Questions about technologies and technical skills
   - Test whether the candidate genuinely understands
     the technologies listed on their CV
   - Include easy, medium, and difficult questions

4. projects
   - Questions about projects listed on the CV
   - Ask about the candidate's specific contributions
   - Ask about architecture, implementation, challenges,
     decisions, testing, and results

5. experience
   - Questions about professional or practical experience
   - Ask about responsibilities and achievements

6. certifications
   - Questions about knowledge gained from certifications
   - Ask how the candidate applied that knowledge

7. behavioral
   - Questions about teamwork, problem solving,
     failure, communication, leadership, and learning

8. critical_thinking
   - Challenging questions that require the candidate
     to reason rather than simply recall facts

For technical and project questions, include a difficulty:
"easy", "medium", or "hard".

Each question should have this structure:

{{
    "question": "...",
    "difficulty": "...",
    "topic": "..."
}}

For categories where difficulty is not particularly relevant,
use "general".

IMPORTANT RULES:

- Questions must be relevant to the CV.
- Do not invent experience that isn't present in the CV.
- Do not assume the candidate used a technology unless
  the CV indicates it.
- Avoid asking duplicate questions.
- Prefer specific questions over generic questions.
- Questions should sound like questions an actual
  interviewer would ask.
- Include approximately 3-5 questions per category.
- Return ONLY valid JSON.
"""

    print("\nGenerating interview questions...\n")

    response = ollama.chat(
        model="qwen3:8b",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a professional technical interviewer "
                    "who specializes in evaluating candidates."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    result = response["message"]["content"].strip()

    # Remove Markdown code fences if the LLM adds them
    if result.startswith("```json"):
        result = result[7:]

    elif result.startswith("```"):
        result = result[3:]

    if result.endswith("```"):
        result = result[:-3]

    result = result.strip()

    return json.loads(result)


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

    # Ask user for JSON filename
    filename = input("\nEnter resume JSON filename: ")

    # Find the file
    json_path = find_json_file(filename)

    print(f"\nFound JSON file:")
    print(json_path)

    # Load CV
    resume = load_resume(json_path)

    # Generate questions
    questions = generate_questions(resume)

    # Build output
    output = {
        "candidate": resume.get("name"),
        "source_file": json_path.name,
        "questions": questions
    }

    # Save next to the input JSON
    output_path = json_path.parent / "interview_questions.json"

    save_questions(output, output_path)

    print("\nDone!")


if __name__ == "__main__":
    main()