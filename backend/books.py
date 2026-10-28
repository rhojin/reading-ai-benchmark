"""Download a public-domain book from Project Gutenberg and split it into chapters."""
import hashlib
import re

import requests

import config

START = re.compile(r"^\*\*\* START OF THE PROJECT GUTENBERG EBOOK .*$", re.MULTILINE)
END = re.compile(r"^\*\*\* END OF THE PROJECT GUTENBERG EBOOK .*$", re.MULTILINE)
# A chapter starts with a line like "CHAPTER I." and has its title on the next line.
# The table of contents is indented, so its lines don't match.
HEADING = re.compile(r"^CHAPTER ([IVXLC]+)\.\n(.+)$", re.MULTILINE)


def fetch(gutenberg_id):
    """Returns {book_id, title, author, source_url, chapters}. Downloads the book only once."""
    url = config.GUTENBERG_URL.format(id=gutenberg_id)
    path = config.BOOKS_DIR / f"pg{gutenberg_id}.txt"  # books/ is git-ignored
    if not path.exists():
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        config.BOOKS_DIR.mkdir(exist_ok=True)
        path.write_bytes(response.content)
    raw = path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
    return parse(raw, url)


def parse(raw, source_url):
    start, end = START.search(raw), END.search(raw)
    if not (start and end):
        raise ValueError("Project Gutenberg start/end markers not found")
    header, body = raw[:start.start()], raw[start.end():end.start()].strip()

    headings = list(HEADING.finditer(body))
    if not headings:
        raise ValueError("no chapter headings found")
    chapters = []
    for i, heading in enumerate(headings):
        text_end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        chapters.append({
            "chapter_no": i + 1,
            "title": heading.group(2).strip(),
            "text": body[heading.end():text_end].strip(),
        })
    chapters[-1]["text"] = re.sub(r"\s*THE END$", "", chapters[-1]["text"])

    return {
        # The ID is a hash of the book text itself: the same book always gets
        # the same ID, no matter where or when it was downloaded.
        "book_id": hashlib.sha256(body.encode("utf-8")).hexdigest()[:16],
        "title": _header_field(header, "Title"),
        "author": _header_field(header, "Author"),
        "source_url": source_url,
        "chapters": chapters,
    }


def _header_field(header, name):
    match = re.search(rf"^{name}: (.+)$", header, re.MULTILINE)
    return match.group(1).strip() if match else "unknown"
