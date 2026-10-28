"""Writes results.md (to read and share), results.json (the raw numbers) and
questions.json (every model's stored question set).

Run it on its own to rebuild results.md from results.json, questions.json and
quality_review.json - no API calls and no database needed:

    python report.py
"""
import html
import json

import config
from backend import actions, db
from backend.actions import LEVELS, PER_LEVEL
from backend.age_mix import AGE_GROUPS, pick_questions_for_age

SEQUENTIAL, PARALLEL = "sequential_summary", "parallel_no_summary"
VENDOR_NAMES = {"anthropic": "Anthropic", "openai": "OpenAI"}

COMPARISON_ROWS = [  # (row label, key in comparison_cells())
    ("List price per 1M tokens (input / output)", "price"),
    ("Reasoning effort", "reasoning"),
    ("**Time per book**: sequential, with summary", "seq_total"),
    ("**Time per book**: {workers} parallel, no summary", "par_total"),
    ("**Time to first chapter**: sequential, with summary", "seq_first"),
    ("**Time to first chapter**: {workers} parallel, no summary", "par_first"),
    ("Average time per chapter (one request)", "per_chapter"),
    ("**Cost per book**: with summary", "seq_cost"),
    ("**Cost per chapter**: with summary", "seq_cost_chapter"),
    ("Cost per book: no summary", "par_cost"),
    ("Tokens per book with summary: prompt / completion (reasoning)", "tokens"),
    ("**Invalid JSON replies** (both modes)", "invalid"),
    ("Retries after rate limits / server errors", "retries"),
    ("**Extra cost of the running summary**", "extra_cost"),
    ("Extra tokens per book from the summary: prompt / completion", "extra_tokens"),
]


def write(results):
    """After a benchmark run: save the raw numbers and every stored question set, then the report."""
    save_json(config.RESULTS_JSON, rounded(results))
    save_json(config.QUESTIONS_JSON, export_questions(results))
    write_markdown(results)


def write_markdown(results):
    questions = json.loads(config.QUESTIONS_JSON.read_text(encoding="utf-8"))
    config.RESULTS_MD.write_text(markdown(results, collect_samples(results, questions)), encoding="utf-8")


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def rounded(value):
    """Round floats to 6 significant digits so results.json stays readable."""
    if isinstance(value, float):
        return float(f"{value:.6g}")
    if isinstance(value, dict):
        return {key: rounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [rounded(item) for item in value]
    return value


def markdown(results, samples):
    book, models, settings = results["book"], results["models"], results["settings"]
    tested = book["chapters_tested"]
    lines = [
        "# Reading AI Benchmark",
        "",
        "Speed and cost of AI-generated reading-comprehension questions per book chapter, for big and small models.",
        "",
        f"- **Book:** {book['title']} by {book['author']} (Project Gutenberg #{book['gutenberg_id']}, "
        f"book_id `{book['book_id']}`), {tested} of {book['chapters_in_book']} chapters",
        f"- **Questions:** {PER_LEVEL * len(LEVELS)} per chapter ({PER_LEVEL} easy, {PER_LEVEL} medium, "
        f"{PER_LEVEL} hard), each with a short expected answer",
        f"- **Run:** {results['generated_at'][:16].replace('T', ' ')} UTC, spent {usd(results['budget']['spent_usd'])} "
        f"of the {usd(results['budget']['limit_usd'])} budget",
        "- **Costs** are the real costs OpenRouter reported for each request (usage accounting), not estimates.",
        "- **Scope:** one book and one run per mode, so timings vary. Read times are measured on the server, "
        "without the network a real app adds. The quality check covers the two sample chapters only.",
    ]
    if tested < book["chapters_in_book"]:
        lines += ["", f"> **Test run:** only the first {tested} chapters, so \"per book\" below means "
                      f"these {tested} chapters."]
    if results["budget"]["stopped"]:
        lines += ["", "> **Stopped by the budget limit:** some numbers below are incomplete."]
    skipped = [m["model_id"] for m in models.values() if m["parallel_skipped"]]
    if skipped:
        lines += ["", f"> **Parallel run skipped** for {', '.join(skipped)}: it would not have fit in the "
                      "remaining budget."]
    if results["error"]:
        lines += ["", f"> **Run ended early:** {text(results['error'])}"]
    for note in results.get("notes", []):  # hand-written remarks about this run, kept in results.json
        lines += ["", f"> **Note:** {text(note)}"]

    sections = [
        section_comparison(models, settings),
        section_first_questions(models),
        section_reload(models, settings),
        section_families(models, settings),
        section_samples(models, samples),
        section_quality(models),
        section_age_mix(age_example(models, samples)),
    ]
    for number, (title, body) in enumerate([section for section in sections if section], 1):
        lines += ["", f"## {number}. {title}", ""] + body
    lines += section_method(settings)
    return "\n".join(lines) + "\n"


# --- Sections: each returns (title, lines) or None ----------------------------

def section_comparison(models, settings):
    cells = {key: comparison_cells(m) for key, m in models.items()}
    rows = [[label.format(workers=settings["parallel_workers"])] + [cells[key][field] for key in models]
            for label, field in COMPARISON_ROWS]
    notes = [
        "",
        "- *Time to first chapter*: until chapter 1's questions were validated and stored, "
        "i.e. when a family can start reading.",
        "- *Extra cost of the running summary*: run with summary (in and out) minus run without, compared "
        "chapter by chapter. The prompt-token difference is exact; completion tokens also vary a little "
        "from run to run.",
    ]
    no_thinking = [f"`{short_name(m)}` (effort `{m['reasoning']['effort']}`)" for m in models.values()
                   if m["reasoning"].get("effort", "none") != "none"
                   and sum(run["reasoning_tokens"] for run in runs_of(m)) == 0]
    if no_thinking:
        notes.append(f"- *Reasoning*: {' and '.join(no_thinking)} reported 0 reasoning tokens, i.e. they "
                     "answered without a separate thinking step.")
    return "Model comparison", table([""] + model_headers(models), rows, right_align=True) + notes


def comparison_cells(m):
    seq, par = m["runs"][SEQUENTIAL], m["runs"][PARALLEL] or {}
    runs = runs_of(m)
    price, extra = m["price_per_million_tokens"], m["summary_overhead"]
    invalid = sum(run["invalid_json"] for run in runs)
    replies = sum(run["responses"] for run in runs)
    failed = sum(not row["ok"] for run in runs for row in run["per_chapter"])
    compared = ""
    if extra and extra["chapters_compared"] < seq["chapters"]:
        compared = f", from {extra['chapters_compared']} of {seq['chapters']} chapters"
    return {
        "price": f"{list_price(price['input_per_million'])} / {list_price(price['output_per_million'])}",
        "reasoning": m["reasoning"].get("effort", "model default"),
        "seq_total": secs(seq["total_seconds"]),
        "par_total": secs(par.get("total_seconds")),
        "seq_first": secs(seq["first_chapter_seconds"]),
        "par_first": secs(par.get("first_chapter_seconds")),
        "per_chapter": secs(seq["avg_seconds_per_chapter"]),
        "seq_cost": usd(seq["cost_usd"]),
        "seq_cost_chapter": usd(seq["cost_per_chapter_usd"]),
        "par_cost": usd(par.get("cost_usd")),
        "tokens": f"{seq['prompt_tokens']:,} / {seq['completion_tokens']:,} ({seq['reasoning_tokens']:,})",
        "invalid": f"{invalid} of {replies}" + (f", {failed} chapter(s) failed" if failed else ""),
        "retries": str(sum(run["http_retries"] for run in runs)),
        "extra_cost": (f"{signed_usd(extra['cost_usd'])} per book ({percent(extra['cost_percent'])}{compared})"
                       if extra else "-"),
        "extra_tokens": f"{extra['prompt_tokens']:+,} / {extra['completion_tokens']:+,}" if extra else "-",
    }


def section_first_questions(models):
    """How long until a family can start: whole book -> chapter 1 first -> chapter 1 by a small model."""
    vendors, columns, findings = [], [], []
    for vendor in dict.fromkeys(vendor_of(m) for m in models.values()):
        by_size = {m["size"]: m for m in models.values() if vendor_of(m) == vendor}
        if not {"small", "big"} <= by_size.keys():
            continue
        small, big = by_size["small"]["runs"], by_size["big"]["runs"]
        whole_book = big[SEQUENTIAL]["total_seconds"]
        big_first, small_first = big[SEQUENTIAL]["first_chapter_seconds"], small[SEQUENTIAL]["first_chapter_seconds"]
        name = VENDOR_NAMES.get(vendor, vendor)
        vendors.append(name)
        columns.append([
            secs(whole_book),
            f"{secs(big_first)} (`{short_name(by_size['big'])}`{retry_note(big[SEQUENTIAL])})",
            f"{secs(small_first)} (`{short_name(by_size['small'])}`{retry_note(small[SEQUENTIAL])})",
        ])
        if None not in (big_first, small_first):
            step = (f"the small model then cut it to {secs(small_first)}" if small_first < big_first
                    else f"the small model was {secs(small_first - big_first)} slower for chapter 1")
            if big[PARALLEL] and small[PARALLEL]:
                step += (f" (parallel run: {secs(small[PARALLEL]['first_chapter_seconds'])} vs. "
                         f"{secs(big[PARALLEL]['first_chapter_seconds'])})")
            findings.append(f"- **{name}:** showing chapter 1 first cut the wait from {secs(whole_book)} to "
                            f"{secs(big_first)}; {step}.")
    if not columns:
        return None
    labels = [
        "App waits for the whole book (big model, sequential)",
        "App shows chapter 1 first (big model)",
        "Chapter 1 written by the small model instead",
    ]
    rows = [[label] + [column[i] for column in columns] for i, label in enumerate(labels)]
    return "Time until the first questions", [
        "A family can start reading as soon as chapter 1's questions exist. Chapter 2's are only needed once the "
        "child has finished chapter 1, so the rest of the book can be generated in the background. The table "
        "separates the two steps: showing chapter 1 first, and letting a faster small model write it "
        "(times from the sequential runs).",
        "",
    ] + table([""] + vendors, rows, right_align=True) + [""] + findings


def section_reload(models, settings):
    labels = [
        "Generate all questions again: sequential, with summary",
        f"Generate all questions again: {settings['parallel_workers']} parallel, no summary",
        f"**Load all stored questions from SQLite** (average of {settings['reload_reads']} reads)",
    ]
    columns = []
    for m in models.values():
        seq, par, reload = m["runs"][SEQUENTIAL], m["runs"][PARALLEL] or {}, m["cached_reload"]
        columns.append([
            f"{secs(seq['total_seconds'])}, {usd(seq['cost_usd'])}",
            f"{secs(par.get('total_seconds'))}, {usd(par.get('cost_usd'))}",
            f"{ms(reload['avg_ms'])} for {reload['questions']} questions, $0",
        ])
    rows = [[label] + [column[i] for column in columns] for i, label in enumerate(labels)]
    return "Second family: load from SQLite vs. generate again", table(
        [""] + model_headers(models), rows, right_align=True) + [
        "",
        "The read time is measured inside the server process. A real app adds the network round-trip to the "
        "family's device, for stored and freshly generated questions alike.",
    ]


def section_families(models, settings):
    n = settings["families"]
    labels = [
        f"**Without shared storage:** {n:,} × generation",
        f"**With shared storage:** 1 × generation + {n - 1:,} reads from SQLite",
        "Saving",
        "Wait for chapter 1's questions: without → with shared storage",
    ]
    columns = []
    for m in models.values():
        families, seq, reload = m["families"], m["runs"][SEQUENTIAL], m["cached_reload"]
        without, shared = families["without_shared_storage_usd"], families["with_shared_storage_usd"]
        columns.append([
            usd(without),
            usd(shared),
            f"{100 * (1 - shared / without):.1f}%" if without else "-",
            f"{secs(seq['first_chapter_seconds'])} → {ms(reload['avg_ms'])} + network",
        ])
    rows = [[label] + [column[i] for column in columns] for i, label in enumerate(labels)]
    return f"Cost for {n:,} families reading this book", table([""] + model_headers(models), rows,
                                                               right_align=True) + [
        "",
        f"This assumes all {n:,} families read this one book. With many books, the saving depends on how many "
        "families share each book, but a book's questions are always paid for only once. Generation cost = the "
        "sequential run with summary; reads from SQLite make no AI call, so they cost no AI money.",
    ]


def section_samples(models, samples):
    lines = ["The stored question sets (sequential run, with running summary), grouped by level, so you can judge "
             "the quality yourself. Every chapter of every model is in [`questions.json`](questions.json)."]
    for sample in samples:
        rows = []
        for level in LEVELS:
            for i in range(PER_LEVEL):
                row = [level]
                for key in models:
                    of_level = [q for q in sample["models"][key]["questions"] if q["level"] == level]
                    row.append(qa_cell(of_level[i]) if i < len(of_level) else "-")
                rows.append(row)
        rows.append(["*summary*"] + [cell(sample["models"][key]["summary"] or "-") for key in models])
        lines += ["", f"### Chapter {sample['chapter_no']}: {text(sample['title'])}", ""]
        lines += table(["Level"] + model_headers(models), rows)
    return "Sample chapters side by side", lines


def section_quality(models):
    """Usable questions per model for the sample chapters, from the manual review in quality_review.json."""
    if not config.QUALITY_REVIEW.exists():
        return None
    review = json.loads(config.QUALITY_REVIEW.read_text(encoding="utf-8"))
    title = f"Quality check: usable questions for a child of {review['ages']}"
    if review["runs"] != {key: m["stored_set_run_id"] for key, m in models.items()}:
        return title, ["*Not reviewed for this run: `quality_review.json` refers to the questions of other runs.*"]
    chapters, per_chapter = review["chapters"], PER_LEVEL * len(LEVELS)
    with_two_part = all("two_part" in review["ratings"][key] for key in models)
    rows = []
    for key, m in models.items():
        ratings = review["ratings"][key]
        problems = [f"Ch. {no}: {ratings[str(no)]['why_not']}" for no in chapters if ratings[str(no)]["why_not"]]
        rows.append(model_headers({key: m})
                    + [f"{ratings[str(no)]['usable']}/{per_chapter}" for no in chapters]
                    + ([f"{ratings['two_part']}/{per_chapter * len(chapters)}"] if with_two_part else [])
                    + [cell(" ".join(problems) or "-")])
    header = (["Model"] + [f"Chapter {no}" for no in chapters] + (["Asks two things"] if with_two_part else [])
              + ["Not usable, and why"])
    criterion = review.get("criterion", "A question counts as usable if a parent could ask it as written: clear "
                                        "for the age, answerable from the story, with a correct expected answer.")
    return title, [f"Reviewer: {text(review['reviewer'])}. {text(criterion)}", ""] + table(header, rows)


def section_age_mix(example):
    rules = "; ".join(
        f"{group['ages']}: " + ", ".join(f"{n} {level}" for level, n in group["mix"].items() if n)
        for group in AGE_GROUPS
    )
    lines = [f"`pick_questions_for_age()` in `backend/age_mix.py` picks from the stored set of chapter "
             f"{example['chapter_no']} ({text(example['title'])}, `{example['model_id']}`). Rules: {rules}."]
    for age, questions in example["ages"].items():
        lines += ["", f"**Age {age}** ({len(questions)} questions)", ""]
        lines += [f"{i}. *{q['level']}*: {text(q['question'])}<br>Expected: {text(q['answer'])}"
                  for i, q in enumerate(questions, 1)]
    return "Age-based mix from the same stored set (no extra AI call)", lines


def section_method(settings):
    workers = settings["parallel_workers"]
    return [
        "",
        "## How it was measured",
        "",
        "- One OpenRouter request per chapter (`/api/v1/chat/completions` with `\"usage\": {\"include\": true}`); "
        "every cost is the `usage.cost` that OpenRouter returned.",
        "- **Sequential, with summary:** one chapter after another. Each prompt contains the 2-3 sentence "
        "summaries of all earlier chapters, and the reply adds one for the current chapter.",
        f"- **{workers} parallel, no summary:** {workers} requests at a time; the chapters don't depend on each other.",
        "- **Run order:** every model's sequential run first (cheap models first), then the parallel runs. "
        "A parallel run only starts if it fits in the remaining budget.",
        "- **Reasoning:** every model runs at the lowest reasoning effort it allows. Reasoning tokens are billed "
        "as completion tokens and are included in all costs.",
        "- **Invalid JSON:** a reply that isn't valid JSON or doesn't contain exactly 2 easy, 2 medium and 2 hard "
        "questions (plus the summary in sequential mode). The chapter is then requested again.",
        f"- **Second family:** `load_book_questions()` opens SQLite, reads all stored questions of the book and "
        f"returns them; the time is the average of {settings['reload_reads']} reads.",
        "- Timings come from single runs and vary with network and provider load.",
        "- OpenAI caches repeated prompts automatically for a while, and cached input is much cheaper. "
        "A run shortly after an earlier one can therefore look cheaper for OpenAI models.",
        "- Prompts: [`prompts/`](prompts/). Raw numbers, including per-chapter rows: [`results.json`](results.json). "
        "Every stored question set: [`questions.json`](questions.json). The local `benchmark.db` (not in git) "
        "holds everything, including earlier test runs.",
    ]


# --- Data for the sections ---------------------------------------------------------

def export_questions(results):
    """Every model's stored question set, read from SQLite, so readers can see all of it without the database."""
    book_id, tested = results["book"]["book_id"], results["book"]["chapters_tested"]
    export = {"book_id": book_id,
              "chapters": {str(c["chapter_no"]): c["title"] for c in actions.list_chapters(book_id)[:tested]},
              "models": {}}
    for key, m in results["models"].items():
        run_id = m["stored_set_run_id"]
        summaries = {str(row["chapter_no"]): row["summary"] for row in db.run_chapters(run_id)}
        by_chapter = {}
        for q in actions.load_book_questions(book_id, run_id):
            by_chapter.setdefault(str(q["chapter_no"]), []).append(
                {"level": q["level"], "question": q["question"], "answer": q["answer"]})
        export["models"][key] = {
            "model_id": m["model_id"],
            "run_id": run_id,
            "chapters": {no: {"summary": summaries.get(no), "questions": by_chapter.get(no, [])}
                         for no in export["chapters"]},
        }
    return export


def collect_samples(results, questions):
    """First and last tested chapter, with every model's stored questions and summary."""
    numbers = list(questions["chapters"])  # "1", "2", ... in chapter order
    return [{"chapter_no": int(no),
             "title": questions["chapters"][no],
             "models": {key: questions["models"][key]["chapters"][no] for key in results["models"]}}
            for no in dict.fromkeys([numbers[0], numbers[-1]])]


def age_example(models, samples):
    """Age 7 and age 10 picks from one stored set: first sample chapter, first big model that ran."""
    key = next((key for key, m in models.items() if m["size"] == "big"), next(iter(models)))
    chapter = samples[0]
    questions = chapter["models"][key]["questions"]
    return {
        "chapter_no": chapter["chapter_no"],
        "title": chapter["title"],
        "model_id": models[key]["model_id"],
        "ages": {age: pick_questions_for_age(questions, age) for age in (7, 10)},
    }


# --- Formatting helpers --------------------------------------------------------

def model_headers(models):
    return [f"{m['size'].capitalize()}: `{m['model_id']}`" for m in models.values()]


def runs_of(model):
    return [run for run in model["runs"].values() if run]


def retry_note(run):
    """', incl. 1 JSON retry' if the run's first chapter needed more than one reply."""
    retries = run["per_chapter"][0]["responses"] - 1 if run["per_chapter"] else 0
    return f", incl. {retries} JSON {'retry' if retries == 1 else 'retries'}" if retries > 0 else ""


def vendor_of(model):
    return model["model_id"].split("/")[0]


def short_name(model):
    return model["model_id"].split("/", 1)[1]


def table(header, rows, right_align=False):
    align = ["---"] + ["---:" if right_align else "---"] * (len(header) - 1)
    return ["| " + " | ".join(row) + " |" for row in [header, align, *rows]]


def usd(value):
    """Dollar amounts, with more decimals for the tiny per-chapter costs of small models."""
    if value is None:
        return "-"
    if abs(value) >= 1:
        return f"${value:,.2f}"
    return f"${value:.4f}" if abs(value) >= 0.01 else f"${value:.5f}"


def list_price(value):
    """Price per 1M tokens: $0.10, $2.00, $0.825."""
    return f"${value:.2f}" if round(value, 2) == round(value, 6) else f"${value:.3f}"


def signed_usd(value):
    return ("+" if value >= 0 else "-") + usd(abs(value))


def percent(value):
    return "-" if value is None else f"{value:+.0f}%"


def secs(value):
    return "-" if value is None else f"{value:.1f} s"


def ms(value):
    return f"{value:.2f} ms"


def text(value):
    """Plain text made safe for Markdown (no stray HTML, no line breaks)."""
    return html.escape(" ".join(str(value).split()), quote=False)


def cell(value):
    return text(value).replace("|", "\\|")


def qa_cell(question):
    return f"**Q:** {cell(question['question'])}<br>**A:** {cell(question['answer'])}"


if __name__ == "__main__":
    write_markdown(json.loads(config.RESULTS_JSON.read_text(encoding="utf-8")))
    print(f"Rebuilt {config.RESULTS_MD.name} from {config.RESULTS_JSON.name} and {config.QUESTIONS_JSON.name}.")
