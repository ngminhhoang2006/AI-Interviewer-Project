import json
from pathlib import Path
from datetime import datetime


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

QUESTIONS_FILE = BASE_DIR / "interview_questions.json"


# ============================================================
# LOAD QUESTIONS
# ============================================================

def load_questions():

    if not QUESTIONS_FILE.exists():
        raise FileNotFoundError(
            f"\nCould not find:\n{QUESTIONS_FILE}"
        )

    print(f"\nLoading questions from:")
    print(QUESTIONS_FILE)

    with open(QUESTIONS_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


# ============================================================
# EXTRACT QUESTIONS
# ============================================================

def extract_questions(data):

    questions = data.get("questions", [])

    all_questions = []

    # Your JSON uses a list of questions
    if isinstance(questions, list):

        for index, question in enumerate(questions, start=1):

            all_questions.append({
                "question_number": index,
                "category": question.get("category"),
                "question": question.get("question"),
                "difficulty": question.get("difficulty"),
                "topic": question.get("topic")
            })

    # Also support the older dictionary format
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
# RUN INTERVIEW
# ============================================================

def run_interview(candidate_name, questions):

    answers = []

    # Limit interview to 10 questions, feel free to adjust this number as needed
    questions = questions[:10]

    print("\n")
    print("=" * 70)
    print("                 AI INTERVIEW")
    print("=" * 70)

    print(f"\nCandidate: {candidate_name}")
    print(f"Total questions: {len(questions)}")

    print("\nThe interview will begin now.")
    print("Type your answer and press ENTER.")
    print("You will be asked to confirm each answer.")
    print("Type 'quit' at any time to stop the interview.")

    input("\nPress ENTER to begin...")

    for index, question_data in enumerate(questions, start=1):

        print("\n")
        print("-" * 70)

        print(f"Question {index}/{len(questions)}")
        print(f"Category: {question_data['category']}")

        if question_data["difficulty"]:
            print(f"Difficulty: {question_data['difficulty']}")

        if question_data["topic"]:
            print(f"Topic: {question_data['topic']}")

        print()
        print(question_data["question"])
        print()

        # ----------------------------------------------------
        # GET AND CONFIRM ANSWER
        # ----------------------------------------------------

        while True:

            answer = input("Your answer: ")

            # Allow the candidate to quit
            if answer.strip().lower() == "quit":

                print("\nInterview stopped.")
                return answers

            print()
            print(f"Your answer: {answer}")
            print()

            confirmation = input(
                "Are you sure this is your answer? (yes/no): "
            ).strip().lower()

            if confirmation in ["yes", "y"]:

                break

            elif confirmation in ["no", "n"]:

                print("\nOkay, please enter your answer again.\n")

            else:

                print(
                    "\nPlease enter 'yes' or 'no'.\n"
                )

        # ----------------------------------------------------
        # SAVE ANSWER
        # ----------------------------------------------------

        answers.append({
            "question_number": index,
            "category": question_data["category"],
            "topic": question_data["topic"],
            "difficulty": question_data["difficulty"],
            "question": question_data["question"],
            "answer": answer
        })

    return answers


# ============================================================
# SAVE ANSWERS
# ============================================================
def get_next_output_file():
    """
    Find the next available interview_answers_XXX.json filename.
    """

    number = 1

    while True:

        filename = f"interview_answers_{number:03d}.json"
        output_path = BASE_DIR / filename

        if not output_path.exists():
            return output_path

        number += 1


def save_answers(candidate_name, answers):

    output = {
        "candidate": candidate_name,
        "source_questions": QUESTIONS_FILE.name,
        "interview_date": datetime.now().isoformat(),
        "total_answered": len(answers),
        "answers": answers
    }

    # Find a unique filename
    output_path = get_next_output_file()

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

    print("=" * 70)
    print("              AI INTERVIEW CHATBOT")
    print("=" * 70)

    # Automatically load interview_questions.json
    data = load_questions()

    candidate_name = data.get(
        "candidate",
        "Unknown Candidate"
    )

    questions = extract_questions(data)

    if not questions:

        print("\nNo questions were found in interview_questions.json.")
        return

    # Run interview
    answers = run_interview(
        candidate_name,
        questions
    )

    # Save answers
    save_answers(
        candidate_name,
        answers
    )

    print("\n")
    print("=" * 70)
    print("                 INTERVIEW COMPLETE")
    print("=" * 70)

    print(
        f"\nQuestions answered: "
        f"{len(answers)}"
    )


if __name__ == "__main__":
    main()