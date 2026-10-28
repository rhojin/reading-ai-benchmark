"""The backend's actions: the only functions the client calls.

    client -> generate_questions(book_id, chapter_no) -> backend -> AI (OpenRouter)
    client -> load_book_questions(book_id, run_id)    -> backend -> SQLite only, no AI

The client sends IDs and options, never prompt text. The prompt is built here,
from the templates in prompts/ and the chapter text stored in SQLite.
"""
import json
import time

import config
from backend import books, db, llm, prompts

LEVELS = ("easy", "medium", "hard")
PER_LEVEL = 2  # questions per level - must match prompts/system.md


class InvalidReply(Exception):
    """The model's reply was not the JSON we asked for."""


def import_book(gutenberg_id):
    """Download the book (once), split it into chapters and store it. Returns its book_id."""
    book = books.fetch(gutenberg_id)
    db.save_book(book)
    return book["book_id"]


def get_book(book_id):
    return db.get_book(book_id)


def list_chapters(book_id):
    return db.list_chapters(book_id)


def generate_questions(book_id, chapter_no, *, run_id, model_key, with_story):
    """Generate the question set for one chapter with the AI, validate it and store it.

    with_story=True adds the running summary of the earlier chapters to the prompt
    and asks for a summary of this chapter, which the next chapter then receives.
    """
    started = time.perf_counter()
    model = config.MODELS[model_key]
    book = db.get_book(book_id)
    chapter = db.get_chapter(book_id, chapter_no)
    story = prompts.story_so_far(db.story_so_far(run_id, chapter_no)) if with_story else None
    messages = prompts.question_messages(book, chapter, story)

    stats = {"responses": 0, "invalid_json": 0, "http_retries": 0, "prompt_tokens": 0,
             "completion_tokens": 0, "reasoning_tokens": 0, "cost_usd": 0.0, "provider": None}
    questions = summary = None
    try:
        while questions is None and stats["responses"] <= config.JSON_RETRIES:
            reply = llm.chat(model, messages)
            stats["responses"] += 1
            for key in ("http_retries", "prompt_tokens", "completion_tokens", "reasoning_tokens", "cost_usd"):
                stats[key] += reply[key]
            stats["provider"] = reply["provider"]
            try:
                questions, summary = parse_reply(reply, with_summary=with_story)
            except InvalidReply as problem:
                stats["invalid_json"] += 1
                print(f"    chapter {chapter_no}: invalid reply ({problem})")
    finally:
        # Paid replies are always recorded, even when the budget stops the run halfway.
        stats["seconds"] = time.perf_counter() - started
        if stats["responses"]:
            db.save_chapter_result(run_id, book_id, chapter_no, stats, questions, summary)
    return {"chapter_no": chapter_no, "ok": questions is not None, **stats}


def parse_reply(reply, with_summary):
    """Check a reply against the JSON we asked for. Returns (questions, summary)."""
    if reply["finish_reason"] == "length":
        raise InvalidReply("cut off at max_tokens")
    text = reply["text"]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise InvalidReply("no JSON object found")
    try:
        data = json.loads(text[start:end + 1])  # tolerates code fences around the JSON
    except json.JSONDecodeError as error:
        raise InvalidReply(f"JSON syntax error: {error.msg}") from None
    items = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise InvalidReply('no "questions" list')

    questions = []
    for item in items:
        if not isinstance(item, dict):
            raise InvalidReply("a question is not a JSON object")
        level = str(item.get("level", "")).strip().lower()
        if level not in LEVELS or not _is_text(item.get("question")) or not _is_text(item.get("answer")):
            raise InvalidReply(f"incomplete question {json.dumps(item)[:80]}")
        questions.append({"level": level, "question": item["question"].strip(), "answer": item["answer"].strip()})

    counts = {level: [q["level"] for q in questions].count(level) for level in LEVELS}
    if set(counts.values()) != {PER_LEVEL}:
        raise InvalidReply(f"expected {PER_LEVEL} questions per level, got {counts}")

    summary = data.get("chapter_summary")
    if with_summary and not _is_text(summary):
        raise InvalidReply('no "chapter_summary"')
    return questions, (summary.strip() if with_summary else None)


def load_book_questions(book_id, run_id):
    """What every later family gets: the stored question set, read from SQLite. No AI call.
    (run_id picks which generated set to read: one per model and mode in this benchmark.)"""
    return db.book_questions(book_id, run_id)


def _is_text(value):
    return isinstance(value, str) and value.strip() != ""
