"""Pick an age-appropriate mix from a chapter's stored question set - no AI call.

Each chapter's set is generated once (2 easy, 2 medium, 2 hard) and stored.
Every family then gets the mix that fits their child's age, straight from storage.
"""

AGE_GROUPS = [
    {"ages": "up to 7", "max_age": 7, "mix": {"easy": 2, "medium": 1, "hard": 0}},  # mostly easy
    {"ages": "8-9", "max_age": 9, "mix": {"easy": 1, "medium": 2, "hard": 1}},
    {"ages": "10+", "max_age": None, "mix": {"easy": 0, "medium": 2, "hard": 2}},  # medium and hard
]


def mix_for_age(age):
    """How many questions of each level a child of this age gets."""
    for group in AGE_GROUPS:
        if group["max_age"] is None or age <= group["max_age"]:
            return group["mix"]


def pick_questions_for_age(questions, age):
    """questions: one chapter's stored set. Returns the questions for this age, easiest first."""
    picked = []
    for level, count in mix_for_age(age).items():
        picked += [q for q in questions if q["level"] == level][:count]
    return picked
