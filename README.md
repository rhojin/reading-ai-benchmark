# Reading AI Benchmark

How fast and how expensive is it to have an AI write reading-comprehension questions for every chapter of a children's book, and what does it save to store them once and share them? This small benchmark measures it. It runs a big and a small model from two vendors (Anthropic and OpenAI) through OpenRouter on *Alice's Adventures in Wonderland* (Project Gutenberg #11, 12 chapters).

For each chapter the AI writes 6 questions with short expected answers as JSON: 2 easy (facts), 2 medium (why/how) and 2 hard (opinion, prediction, connecting events). The set is generated **once** and stored in SQLite. Every later family reads it from there, and an age-appropriate mix is picked from the stored set without another AI call.

**Results: [results.md](results.md)** · raw numbers: [results.json](results.json) · every generated question: [questions.json](questions.json)

## Findings (run of 2026-10-28)

- **First questions:** chapter 1 took 3-10 s depending on the model, the whole book 10-140 s. So the app should show chapter 1 first and generate the rest in the background; that is the biggest win. A small model for chapter 1 helped further with OpenAI (10 s → 3 s), but not clearly with Anthropic.
- **Shared storage:** stored once, all 72 questions of the book are read back from SQLite in about 0.6 ms on the server (a real app adds the network round-trip), with no AI cost. Generating costs $0.007-0.21 per book, paid once instead of once per family.
- **Model size:** the small models were 16-22× cheaper per book than the big ones. A spot check of the questions is in [results.md](results.md) (section 6).

## Limits

- One book and one run per mode, so timings vary with network and provider load.
- Read times are measured inside the server process, without the network.
- The quality check covers 2 of the 12 chapters and is a quick review, not a teacher's assessment.
- `backend/` is the backend logic only: there is no web server, no logins and no per-user limits. It does show the split a real backend needs: the client sends only IDs (book, chapter) and the prompts are built on the server from templates, so in a real app neither prompt text nor AI credentials would reach the user's device.

## What you need

- Windows with **Git Bash** (macOS/Linux work too, see the note under Setup)
- **Python 3.9 or newer**: check which command works on your machine, `python --version` or `py --version`
- An **OpenRouter API key** from https://openrouter.ai/keys. Each run stops on its own at $1.00 (see Safety).

Everything stays inside this folder: the virtual environment (`.venv/`), the database (`benchmark.db`) and the downloaded book (`books/`). No global installs, no Docker, no services running in the background.

## Setup (Git Bash)

```bash
cd reading-ai-benchmark

# 1. Create the virtual environment inside this folder
#    (use "py" instead of "python" if that is the command that works for you)
python -m venv .venv

# 2. Activate it
source .venv/Scripts/activate

# 3. Install the two dependencies
#    (--no-cache-dir: pip leaves no download cache outside this folder)
python -m pip install --no-cache-dir -r requirements.txt

# 4. Add your API key: paste it after OPENROUTER_API_KEY= and save
cp .env.example .env
notepad .env
```

The key is only read from `.env`, which git ignores, and it is never printed.
On macOS/Linux use `python3 -m venv .venv` and `source .venv/bin/activate`.

## Run

```bash
python run_benchmark.py --model small --chapters 2   # cheap test first: 2 chapters, small models only
python run_benchmark.py                              # everything: all 4 models, all 12 chapters
```

| Option | Meaning |
|---|---|
| `--model big\|small\|both` | which model size(s) to run (default: `both`) |
| `--vendor anthropic\|openai\|all` | which vendor(s) to run (default: `all`) |
| `--chapters N` | only the first N chapters (default: all) |

Each run writes `results.md`, `results.json` and `questions.json` (all meant to be committed) and stores all details in `benchmark.db` (local only, not in git). Models, reasoning effort, budget and the number of parallel requests are set in [`config.py`](config.py).

To rebuild `results.md` without any API calls or database, for example after editing `quality_review.json`, run `python report.py`. It works on a fresh clone too, because it only reads the committed JSON files.

## What it measures

For each model:

1. **Sequential, with running summary:** chapter by chapter. Each prompt includes short summaries of the earlier chapters, so "hard" questions can connect events across the story. The model also returns a 2-3 sentence summary of the chapter, which is passed on to the next one. This makes every chapter wait for the one before it.
2. **4 parallel, no summary:** the chapters are independent, so 4 requests run at the same time.
3. **Second family:** reads all stored questions of the book from SQLite (average of 100 reads).

For every run it records the time per chapter, the total time per book, the time until chapter 1 is ready, prompt and completion tokens, and the real cost per chapter and per book, taken from OpenRouter's usage accounting rather than estimated. The difference between runs 1 and 2 shows what the running summary costs in extra tokens and money.

Every model runs at the lowest reasoning effort it allows (`none` for the small models; the big models can't switch reasoning off, so they use `low`). Reasoning tokens are billed as output tokens and are included in all costs.

## How the code is organised

```
client (run_benchmark.py; in production: the web app)
   |  generate_questions(book_id, chapter_no)      <- IDs only, never prompt text
   v
backend/actions.py   loads the chapter (and the story so far) from SQLite,
   |                 fills the templates in prompts/ (backend/prompts.py),
   |                 validates the JSON reply and stores the questions
   v
backend/llm.py  -->  OpenRouter  (real cost per request, retries with backoff, budget stop)

later families:  load_book_questions(book_id, ...)       -> SQLite only, no AI call
age mix:         pick_questions_for_age(questions, age)  -> from the stored set, no AI call
```

| File | Purpose |
|---|---|
| `run_benchmark.py` | the one command; plays the client |
| `config.py` | models, reasoning effort, budget, parallel requests, paths |
| `report.py` | writes `results.md`, `results.json` and `questions.json`; on its own it rebuilds `results.md` |
| `results.md`, `results.json`, `questions.json` | the report, the raw numbers and every stored question set of the last run |
| `quality_review.json` | manual rating of the sample chapters' questions; shown in `results.md` only while it matches the stored runs |
| `backend/actions.py` | the backend's actions: `import_book`, `generate_questions`, `load_book_questions` |
| `backend/prompts.py`, `prompts/` | the prompt templates and the code that fills them |
| `backend/llm.py` | OpenRouter client: usage accounting, retries, budget stop |
| `backend/books.py` | downloads the book from Project Gutenberg, splits it into chapters, content-hash book ID |
| `backend/db.py` | SQLite schema and queries |
| `backend/age_mix.py` | picks the questions for a child's age from the stored set |

Database tables: `books`, `chapters`, `runs` (one row per model and mode, with totals), `run_chapters` (time, tokens, cost and summary per chapter), `questions`.

## Safety

- **Budget stop:** once a run has spent $1.00 (`BUDGET_USD` in `config.py`), no new request is sent. Requests that are already running (at most 4) still finish. If your OpenRouter key has a spending limit with less than that left, the remaining limit is used as the budget instead.
- **Budget-aware order:** cheap models first, and every model's main run (sequential, with summary) before any parallel run. A parallel run only starts if it fits in what is left of the budget, so you never pay for a half-finished run.
- **Retries:** rate limits (429) and server errors (5xx, timeouts) are retried with exponential backoff (2, 4, 8, 16 s).
- **JSON validation:** every reply must be valid JSON with exactly 2 easy, 2 medium and 2 hard questions. Invalid replies are counted and the chapter is requested again, at most twice more.
- **Model check:** before anything is spent, the configured model IDs are checked against OpenRouter's model list.

## Delete everything

Everything lives in this one folder, so deleting the folder removes everything:

```bash
deactivate                  # if the virtual environment is active
cd ..
rm -rf reading-ai-benchmark
```

You can also delete the folder in Explorer. Nothing was installed globally, and pip ran with `--no-cache-dir`, so nothing is left in your user profile.
