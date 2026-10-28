"""Builds the prompts from the templates in prompts/.

Only the backend fills in templates. The client asks for an action ("questions
for book X, chapter 3") and never sends prompt text, so nobody can use the
backend to send arbitrary text to the AI.
"""
from string import Template

import config


def render(template_name, **values):
    text = (config.PROMPTS_DIR / template_name).read_text(encoding="utf-8")
    return Template(text).substitute(values)


def story_so_far(summaries):
    """Turn the stored chapter summaries into the running "story so far"."""
    if not summaries:
        return "(none yet - this is the first chapter)"
    return "\n".join(f"Chapter {s['chapter_no']} ({s['title']}): {s['summary']}" for s in summaries)


def question_messages(book, chapter, story=None):
    """Chat messages for one chapter. story=None means: no running summary."""
    values = {
        "book_title": book["title"],
        "book_author": book["author"],
        "chapter_no": chapter["chapter_no"],
        "chapter_title": chapter["title"],
        "chapter_text": chapter["text"],
    }
    if story is None:
        user_prompt = render("chapter_questions.md", **values)
    else:
        user_prompt = render("chapter_questions_with_story.md", story_so_far=story, **values)
    return [
        {"role": "system", "content": render("system.md")},
        {"role": "user", "content": user_prompt},
    ]
