"""SQLite storage. Everything lives in one file, benchmark.db, inside the project folder."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    book_id     TEXT PRIMARY KEY,        -- content hash of the book text
    title       TEXT NOT NULL,
    author      TEXT NOT NULL,
    source_url  TEXT NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chapters (
    book_id    TEXT NOT NULL REFERENCES books (book_id),
    chapter_no INTEGER NOT NULL,
    title      TEXT NOT NULL,
    text       TEXT NOT NULL,
    PRIMARY KEY (book_id, chapter_no)
);

-- One row per run: one model generating questions for the book in one mode.
CREATE TABLE IF NOT EXISTS runs (
    run_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id               TEXT NOT NULL REFERENCES books (book_id),
    model_key             TEXT NOT NULL,                    -- e.g. anthropic-big (see config.MODELS)
    model_id              TEXT NOT NULL,
    mode                  TEXT NOT NULL,                    -- sequential_summary / parallel_no_summary
    workers               INTEGER NOT NULL,
    chapters              INTEGER NOT NULL,
    started_at            TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'running',  -- running / done / budget_stop / error
    first_chapter_seconds REAL,                             -- until chapter 1's questions were stored
    total_seconds         REAL,                             -- until all chapters were done
    chapters_ok           INTEGER,
    prompt_tokens         INTEGER,
    completion_tokens     INTEGER,
    reasoning_tokens      INTEGER,
    cost_usd              REAL,                             -- real cost reported by OpenRouter
    invalid_json          INTEGER,
    http_retries          INTEGER
);

-- One row per chapter of a run.
CREATE TABLE IF NOT EXISTS run_chapters (
    run_id            INTEGER NOT NULL REFERENCES runs (run_id),
    chapter_no        INTEGER NOT NULL,
    ok                INTEGER NOT NULL,   -- 1 = valid questions stored
    seconds           REAL NOT NULL,      -- time for this chapter, including retries
    responses         INTEGER NOT NULL,   -- replies received (more than 1 = JSON retry)
    invalid_json      INTEGER NOT NULL,
    http_retries      INTEGER NOT NULL,
    prompt_tokens     INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    reasoning_tokens  INTEGER NOT NULL,
    cost_usd          REAL NOT NULL,
    provider          TEXT,               -- where OpenRouter sent the request
    summary           TEXT,               -- 2-3 sentences, passed on to the next chapter
    PRIMARY KEY (run_id, chapter_no)
);

CREATE TABLE IF NOT EXISTS questions (
    question_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES runs (run_id),
    book_id         TEXT NOT NULL,
    chapter_no      INTEGER NOT NULL,
    level           TEXT NOT NULL CHECK (level IN ('easy', 'medium', 'hard')),
    question        TEXT NOT NULL,
    expected_answer TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS questions_by_book ON questions (book_id, run_id);
"""


@contextmanager
def connect():
    """A short-lived connection per call, like one request in a web backend.
    This also keeps the parallel mode safe: every thread uses its own connection."""
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with connect() as conn:
        conn.executescript(SCHEMA)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _one(sql, params):
    with connect() as conn:
        row = conn.execute(sql, params).fetchone()
    if row is None:
        raise LookupError(f"nothing found for {params}")
    return dict(row)


def _all(sql, params):
    with connect() as conn:
        return [dict(row) for row in conn.execute(sql, params)]


# --- Books and chapters ------------------------------------------------------

def save_book(book):
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO books (book_id, title, author, source_url, imported_at) VALUES (?, ?, ?, ?, ?)",
            (book["book_id"], book["title"], book["author"], book["source_url"], _now()),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO chapters (book_id, chapter_no, title, text) VALUES (?, ?, ?, ?)",
            [(book["book_id"], c["chapter_no"], c["title"], c["text"]) for c in book["chapters"]],
        )


def get_book(book_id):
    return _one("SELECT * FROM books WHERE book_id = ?", (book_id,))


def get_chapter(book_id, chapter_no):
    return _one("SELECT * FROM chapters WHERE book_id = ? AND chapter_no = ?", (book_id, chapter_no))


def list_chapters(book_id):
    return _all("SELECT chapter_no, title FROM chapters WHERE book_id = ? ORDER BY chapter_no", (book_id,))


# --- Generated questions -----------------------------------------------------

def save_chapter_result(run_id, book_id, chapter_no, stats, questions, summary):
    """Store one chapter's outcome: its numbers, its summary and (if valid) its questions."""
    with connect() as conn:
        conn.execute(
            """INSERT INTO run_chapters (run_id, chapter_no, ok, seconds, responses, invalid_json, http_retries,
                                         prompt_tokens, completion_tokens, reasoning_tokens, cost_usd, provider, summary)
               VALUES (:run_id, :chapter_no, :ok, :seconds, :responses, :invalid_json, :http_retries,
                       :prompt_tokens, :completion_tokens, :reasoning_tokens, :cost_usd, :provider, :summary)""",
            {**stats, "run_id": run_id, "chapter_no": chapter_no, "ok": int(questions is not None), "summary": summary},
        )
        conn.executemany(
            "INSERT INTO questions (run_id, book_id, chapter_no, level, question, expected_answer) VALUES (?, ?, ?, ?, ?, ?)",
            [(run_id, book_id, chapter_no, q["level"], q["question"], q["answer"]) for q in questions or []],
        )


def story_so_far(run_id, before_chapter):
    """Summaries of this run's earlier chapters, oldest first."""
    return _all(
        """SELECT rc.chapter_no, c.title, rc.summary
           FROM run_chapters rc
           JOIN runs r     ON r.run_id = rc.run_id
           JOIN chapters c ON c.book_id = r.book_id AND c.chapter_no = rc.chapter_no
           WHERE rc.run_id = ? AND rc.chapter_no < ? AND rc.summary IS NOT NULL
           ORDER BY rc.chapter_no""",
        (run_id, before_chapter),
    )


def book_questions(book_id, run_id):
    """All stored questions of one generated set (run) for a book."""
    return _all(
        """SELECT chapter_no, level, question, expected_answer AS answer
           FROM questions
           WHERE book_id = ? AND run_id = ?
           ORDER BY chapter_no, question_id""",
        (book_id, run_id),
    )


# --- Benchmark runs ----------------------------------------------------------

def create_run(book_id, model_key, model_id, mode, workers, chapters):
    with connect() as conn:
        cursor = conn.execute(
            """INSERT INTO runs (book_id, model_key, model_id, mode, workers, chapters, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (book_id, model_key, model_id, mode, workers, chapters, _now()),
        )
        return cursor.lastrowid


def finish_run(run_id, status, first_chapter_seconds, total_seconds):
    """Store the run's timings and add up its chapters. Returns the finished run."""
    with connect() as conn:
        totals = dict(conn.execute(
            """SELECT COALESCE(SUM(ok), 0)                AS chapters_ok,
                      COALESCE(SUM(prompt_tokens), 0)     AS prompt_tokens,
                      COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                      COALESCE(SUM(reasoning_tokens), 0)  AS reasoning_tokens,
                      COALESCE(SUM(cost_usd), 0.0)        AS cost_usd,
                      COALESCE(SUM(invalid_json), 0)      AS invalid_json,
                      COALESCE(SUM(http_retries), 0)      AS http_retries
               FROM run_chapters WHERE run_id = ?""",
            (run_id,),
        ).fetchone())
        conn.execute(
            """UPDATE runs SET status = :status, first_chapter_seconds = :first_chapter_seconds,
                   total_seconds = :total_seconds, chapters_ok = :chapters_ok,
                   prompt_tokens = :prompt_tokens, completion_tokens = :completion_tokens,
                   reasoning_tokens = :reasoning_tokens, cost_usd = :cost_usd,
                   invalid_json = :invalid_json, http_retries = :http_retries
               WHERE run_id = :run_id""",
            {**totals, "status": status, "first_chapter_seconds": first_chapter_seconds,
             "total_seconds": total_seconds, "run_id": run_id},
        )
    return _one("SELECT * FROM runs WHERE run_id = ?", (run_id,))


def run_chapters(run_id):
    return _all("SELECT * FROM run_chapters WHERE run_id = ? ORDER BY chapter_no", (run_id,))
