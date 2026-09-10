import json
import ollama
from pathlib import Path
from datetime import datetime
import re
import unicodedata

BASE_DIR = Path(__file__).resolve().parent

OLLAMA_MODEL = "qwen3:8b"
MAX_QUESTIONS = 10

def flatten_text(text: str) -> str:
    """
    Strips diacritics, converts Vietnamese đ/Đ, handles non-breaking spaces,
    and removes ALL non-alphanumeric characters for clean string comparison.
    """
    # Replace non-breaking spaces and Vietnamese Đ/đ
    text = text.replace("\u00a0", " ").replace("Đ", "D").replace("đ", "d")
    
    # Strip diacritics
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    
    # Keep only pure lowercase letters and numbers
    return re.sub(r"[^a-z0-9]", "", stripped.casefold())


def find_question_file(candidate_name, language):
    """
    Find the candidate's question JSON file inside their folder regardless of 
    casing, diacritics, or search depth.
    """
    target_candidate = flatten_text(candidate_name)
    target_language = flatten_text(language)

    # Roots to search (current dir and parent directories)
    search_roots = [BASE_DIR, BASE_DIR.parent, BASE_DIR.parent.parent]

    matching_dirs = []
    for root in search_roots:
        if root.exists():
            for d in root.rglob("*"):
                if d.is_dir():
                    folder_flat = flatten_text(d.name)
                    # Match folder name against candidate name
                    if folder_flat and (folder_flat == target_candidate or target_candidate in folder_flat):
                        matching_dirs.append(d)

    # Deduplicate matching folders
    matching_dirs = list(set(matching_dirs))

    if not matching_dirs:
        return None

    # Search for question file inside matched applicant folder(s)
    for folder in matching_dirs:
        for file in folder.rglob("*.json"):
            file_flat = flatten_text(file.name)
            # Check if file contains both the candidate name and interview language
            if target_candidate in file_flat and target_language in file_flat and "questions" in file_flat:
                return file

    return None


def get_question_file():
    print("=== AI Interview Chatbot ===\n")

    candidate_name = input("Candidate name: ").strip()
    language = input("Interview language: ").strip()

    question_file = find_question_file(candidate_name, language)

    if question_file is None:
        expected_filename = f"{candidate_name}_questions_{language}.json"

        print("\nERROR: Question file not found.")
        print(f"Expected file: {expected_filename}")
        print(f"Directory searched: {BASE_DIR}")

        return None, candidate_name, language

    print(f"\nQuestion file found: {question_file.name}")

    return question_file, candidate_name, language


# ============================================================
# LOAD QUESTIONS
# ============================================================

def load_questions(question_file):
    """Load interview questions from the selected JSON file."""
    try:
        with open(question_file, "r", encoding="utf-8") as f:
            return json.load(f)

    except FileNotFoundError:
        raise FileNotFoundError(
            f"Question file not found: {question_file}"
        )

    except json.JSONDecodeError as e:
        raise ValueError(
            f"Invalid JSON in question file: {question_file}\n"
            f"Error: {e}"
        )


# ============================================================
# EXTRACT QUESTIONS
# ============================================================

def extract_questions(data):

    questions = data.get("questions", [])

    all_questions = []

    # Current JSON format: list
    if isinstance(questions, list):

        for index, question in enumerate(questions, start=1):

            all_questions.append({
                "question_number": index,
                "category": question.get("category"),
                "question": question.get("question"),
                "difficulty": question.get("difficulty"),
                "topic": question.get("topic")
            })

    # Older JSON format: dictionary
    elif isinstance(questions, dict):

        for category, category_questions in questions.items():

            for question in category_questions:

                all_questions.append({
                    "category": category,
                    "question": question.get("question"),
                    "difficulty": question.get("difficulty"),
                    "topic": question.get("topic")
                })

    else:

        raise ValueError(
            "Invalid 'questions' format in interview_questions.json"
        )

    return all_questions


# ============================================================
# OLLAMA FOLLOW-UP QUESTION GENERATOR
# ============================================================

def generate_follow_up(
    candidate_name,
    language,
    current_question,
    answer,
    previous_answers
):
    history = "\n".join(
        f"Q: {item['question']}\nA: {item['answer']}"
        for item in previous_answers
    )

    prompt = f"""
You are conducting a professional technical interview.

Candidate: {candidate_name}
Interview language: {language}

Previous interview history:
{history}

Current question:
{current_question}

Candidate's answer:
{answer}

Based on the candidate's answer, decide whether a follow-up
question would meaningfully improve the interview.

If a follow-up is useful:
- Ask exactly ONE follow-up question.
- Make it directly related to the candidate's answer.
- Do not repeat the original question.
- Keep it concise.
- Write the question entirely in {language}.

If no follow-up is useful, respond with exactly:

NO_FOLLOW_UP

Otherwise, respond with ONLY the follow-up question.
"""

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a professional technical interviewer. "
                    "Ask concise, relevant and natural questions."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        think=False
    )

    result = response["message"]["content"].strip()

    if "<think>" in result:
        result = result.split("</think>")[-1].strip()

    if result == "NO_FOLLOW_UP":
        return None

    return result


# ============================================================
# ANSWER CONFIRMATION
# ============================================================

def get_confirmed_answer():

    while True:

        answer = input("Your answer: ")

        if answer.strip().lower() == "quit":
            return None

        print()
        print(f"Your answer: {answer}")
        print()

        confirmation = input(
            "Are you sure this is your answer? (yes/no): "
        ).strip().lower()

        if confirmation in ["yes", "y"]:

            return answer

        elif confirmation in ["no", "n"]:

            print("\nOkay, please enter your answer again.\n")

        else:

            print(
                "\nPlease enter 'yes' or 'no'.\n"
            )


# ============================================================
# RUN INTERVIEW
# ============================================================

def run_interview(candidate_name, language, questions):
    answers = []

    base_question_index = 0
    total_question_count = 0

    while (
        total_question_count < MAX_QUESTIONS
        and base_question_index < len(questions)
    ):
        question_data = questions[base_question_index]

        question = question_data["question"]

        print(f"\nQuestion {total_question_count + 1}:")
        print(question)

        answer = get_confirmed_answer()

        answers.append({
            "question_number": total_question_count + 1,
            "type": "predefined",
            "category": question_data.get("category"),
            "difficulty": question_data.get("difficulty"),
            "topic": question_data.get("topic"),
            "question": question,
            "answer": answer
        })

        total_question_count += 1
        base_question_index += 1

        # Don't generate a follow-up if we've reached the limit
        if total_question_count >= MAX_QUESTIONS:
            break

        # Ask Ollama whether a follow-up is appropriate
        follow_up = generate_follow_up(
            candidate_name=candidate_name,
            language=language,
            current_question=question,
            answer=answer,
            previous_answers=answers[:-1]
        )

        if follow_up:
            print("\nFollow-up question:")
            print(follow_up)

            follow_up_answer = get_confirmed_answer()

            answers.append({
                "question_number": total_question_count + 1,
                "type": "follow_up",
                "category": question_data.get("category"),
                "difficulty": question_data.get("difficulty"),
                "topic": question_data.get("topic"),
                "question": follow_up,
                "answer": follow_up_answer
            })

            total_question_count += 1

    return answers


# ============================================================
# SAVE ANSWERS
# ============================================================

def get_output_file(candidate_name):

    normalized_name = normalize_text(candidate_name)

    filename = f"{normalized_name}_answers.json"

    return BASE_DIR / filename


def save_answers(candidate_name, answers, questions_file, interview_language):

    output = {
        "candidate": candidate_name,
        "source_questions": questions_file.name,
        "interview_language": interview_language,
        "interview_date": datetime.now().isoformat(),
        "total_answered": len(answers),
        "answers": answers
    }

    # Save output into the same folder as questions_file
    output_filename = f"{flatten_text(candidate_name)}_answers.json"
    output_path = questions_file.parent / output_filename

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(
            output,
            file,
            indent=4,
            ensure_ascii=False
        )

    print("\nAnswers saved to:")
    print(output_path)

    return output_path


# ============================================================
# MAIN
# ============================================================

def main():
    question_file, candidate_name, language = get_question_file()

    if question_file is None:
        return

    print(f"\nLoading questions for {candidate_name}...")

    questions_data = load_questions(question_file)
    questions = extract_questions(questions_data)

    if not questions:
        print("ERROR: No questions found in the JSON file.")
        return

    print(f"Loaded {len(questions)} questions.")
    print(f"Interview language: {language}")

    answers = run_interview(
        candidate_name,
        language,
        questions
    )

    save_answers(
        candidate_name,
        answers,
        question_file,
        language
    )


if __name__ == "__main__":
    main()