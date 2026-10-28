"""Run the whole benchmark with one command:  python run_benchmark.py

This script plays the "client" (in production: the parents' web app). It only
calls backend actions with IDs, e.g. generate_questions(book_id, chapter_no).
It never builds or sends prompt text - that happens inside backend/.
"""
import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import config
import report
from backend import actions  # the app's backend API
from backend import db, llm  # benchmark bookkeeping only: the runs table and the budget

SEQUENTIAL = "sequential_summary"
PARALLEL = "parallel_no_summary"
MODE_LABELS = {
    SEQUENTIAL: "sequential, with running summary",
    PARALLEL: f"{config.PARALLEL_WORKERS} parallel, no summary",
}


def main():
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Git Bash shows UTF-8
    if not llm.has_api_key():
        sys.exit("OPENROUTER_API_KEY is missing: copy .env.example to .env and paste your key there.")

    keys = [key for key in config.MODELS
            if args.model in ("both", size_of(key)) and args.vendor in ("all", vendor_of(key))]
    db.init()
    prices = llm.model_prices([config.MODELS[key]["id"] for key in keys])  # stops early on an unknown model
    key_left = llm.key_limit_remaining()  # also stops early if OpenRouter rejects the API key
    if key_left is not None and key_left < llm.budget.limit_usd:
        llm.budget.limit_usd = key_left  # the key's own limit is lower: stop before OpenRouter refuses
    book_id = actions.import_book(config.GUTENBERG_ID)
    book = actions.get_book(book_id)
    all_chapters = actions.list_chapters(book_id)
    chapters = all_chapters[:args.chapters] if args.chapters else all_chapters

    print(f"Book: {book['title']} (book_id {book_id}), chapters 1-{len(chapters)} of {len(all_chapters)}")
    for key in keys:
        price = prices[config.MODELS[key]["id"]]
        print(f"{key:>15}: {config.MODELS[key]['id']} (${price['input_per_million']:.2f} in / "
              f"${price['output_per_million']:.2f} out per 1M tokens)")
    print(f"Budget: ${llm.budget.limit_usd:.2f} for this run")

    runs = {key: {SEQUENTIAL: None, PARALLEL: None, "parallel_skipped": False} for key in keys}
    error = None
    try:
        run_all(book_id, chapters, runs)
    except llm.LLMError as problem:
        error = problem
        print(f"\nERROR: {problem}")

    ran = [key for key in keys if runs[key][SEQUENTIAL]]
    if ran:
        print("\nSecond family: the stored sets read back from SQLite")
        models = {key: model_results(key, book_id, runs[key], prices) for key in ran}
        results = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "book": {
                "book_id": book_id,
                "title": book["title"],
                "author": book["author"],
                "gutenberg_id": config.GUTENBERG_ID,
                "chapters_in_book": len(all_chapters),
                "chapters_tested": len(chapters),
            },
            "settings": {
                "questions_per_level": actions.PER_LEVEL,
                "parallel_workers": config.PARALLEL_WORKERS,
                "reload_reads": config.RELOAD_READS,
                "families": config.FAMILIES,
                "max_tokens": config.MAX_TOKENS,
            },
            "budget": {
                "limit_usd": llm.budget.limit_usd,
                "key_limit_remaining_at_start_usd": key_left,
                "spent_usd": llm.budget.spent_usd,
                "stopped": stopped_by_budget(runs),
            },
            "error": str(error) if error else None,
            "models": models,
        }
        report.write(results)
        print(f"\nWrote {config.RESULTS_MD.name} and {config.RESULTS_JSON.name} (all data is in {config.DB_PATH.name}).")
    print(f"Spent ${llm.budget.spent_usd:.4f} of the ${llm.budget.limit_usd:.2f} budget.")
    if error:
        sys.exit(1)


def run_all(book_id, chapters, runs):
    """Fill `runs`: first every model's main run (sequential, with summary), then the
    parallel runs, cheap models first. If the budget runs short, the most important
    numbers are complete instead of a run being cut off halfway."""
    order = sorted(runs, key=lambda key: size_of(key) == "big")
    for key in order:
        runs[key][SEQUENTIAL] = run_mode(key, book_id, chapters, SEQUENTIAL)
        if runs[key][SEQUENTIAL]["status"] == "budget_stop":
            return
    for key in order:
        # A parallel run costs a bit less than the sequential one (no summary in or out):
        # only start it if a run that expensive still fits.
        if llm.budget.spent_usd + runs[key][SEQUENTIAL]["cost_usd"] > llm.budget.limit_usd:
            runs[key]["parallel_skipped"] = True
            print(f"\n[{key}] {MODE_LABELS[PARALLEL]}: skipped, it would not fit in the remaining budget")
            continue
        runs[key][PARALLEL] = run_mode(key, book_id, chapters, PARALLEL)
        if runs[key][PARALLEL]["status"] == "budget_stop":
            return


def run_mode(key, book_id, chapters, mode):
    """Generate the questions for all chapters with one model in one mode and measure the time."""
    with_story = mode == SEQUENTIAL
    workers = 1 if with_story else min(config.PARALLEL_WORKERS, len(chapters))
    run_id = db.create_run(book_id, key, config.MODELS[key]["id"], mode, workers, len(chapters))
    print(f"\n[{key}] {MODE_LABELS[mode]}")

    def generate(chapter_no):
        return actions.generate_questions(book_id, chapter_no, run_id=run_id, model_key=key, with_story=with_story)

    started = time.perf_counter()
    ready_after = {}  # chapter_no -> seconds from the start until its questions were stored

    def chapter_done(result):
        if result["ok"]:
            ready_after[result["chapter_no"]] = time.perf_counter() - started
        print_chapter(result)

    status = "error"
    try:
        if with_story:
            # Each chapter needs the summaries of the chapters before it: one after another.
            for chapter in chapters:
                chapter_done(generate(chapter["chapter_no"]))
        else:
            # The chapters don't depend on each other: several requests at once, chapter 1 first.
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(generate, chapter["chapter_no"]) for chapter in chapters]
                try:
                    for future in as_completed(futures):
                        chapter_done(future.result())
                except BaseException:
                    pool.shutdown(cancel_futures=True)  # don't start the chapters that are still waiting
                    raise
        status = "done"
    except llm.BudgetExceeded as stop:
        status = "budget_stop"
        print(f"  STOP: {stop}")
    finally:
        total_seconds = time.perf_counter() - started
        run = db.finish_run(run_id, status, ready_after.get(chapters[0]["chapter_no"]), total_seconds)
    print(f"  = {run['total_seconds']:.1f} s in total, first chapter after {secs(run['first_chapter_seconds'])}, "
          f"${run['cost_usd']:.4f}")
    return run_numbers(run)


def run_numbers(run):
    """One run's numbers for results.json, including the per-chapter rows."""
    rows = db.run_chapters(run["run_id"])
    for row in rows:
        del row["run_id"], row["summary"]  # results.json holds numbers; the texts stay in benchmark.db
    return {
        **run,
        "avg_seconds_per_chapter": statistics.mean(r["seconds"] for r in rows) if rows else None,
        "cost_per_chapter_usd": run["cost_usd"] / len(rows) if rows else None,
        "responses": sum(r["responses"] for r in rows),
        "per_chapter": rows,
    }


def model_results(key, book_id, model_runs, prices):
    """All numbers for one model, plus the "second family" reload of its stored set."""
    model = config.MODELS[key]
    sequential, parallel = model_runs[SEQUENTIAL], model_runs[PARALLEL]
    reload = measure_reload(book_id, sequential["run_id"])
    print(f"{key:>15}: {reload['questions']} questions in {reload['avg_ms']:.2f} ms "
          f"(average of {reload['reads']} reads)")
    return {
        "model_id": model["id"],
        "size": size_of(key),
        "reasoning": model["reasoning"],
        "price_per_million_tokens": prices[model["id"]],
        "stored_set_run_id": sequential["run_id"],
        "runs": {SEQUENTIAL: sequential, PARALLEL: parallel},
        "parallel_skipped": model_runs["parallel_skipped"],
        "summary_overhead": summary_overhead(sequential, parallel),
        "cached_reload": reload,
        "families": families_projection(sequential),
    }


def summary_overhead(sequential, parallel):
    """Extra tokens and cost of the running summary: with summary minus without.

    Compared chapter by chapter, using only chapters where both modes got a valid
    reply on the first try - a JSON retry would otherwise distort the difference.
    """
    if not parallel:
        return None
    clean_without = {r["chapter_no"]: r for r in parallel["per_chapter"] if r["ok"] and r["responses"] == 1}
    pairs = [(r, clean_without[r["chapter_no"]]) for r in sequential["per_chapter"]
             if r["ok"] and r["responses"] == 1 and r["chapter_no"] in clean_without]
    if not pairs:
        return None
    per_book = sequential["chapters"] / len(pairs)

    def extra(key):
        return sum(with_[key] - without[key] for with_, without in pairs) * per_book

    cost_without = sum(without["cost_usd"] for _, without in pairs) * per_book
    return {
        "chapters_compared": len(pairs),
        "prompt_tokens": round(extra("prompt_tokens")),
        "completion_tokens": round(extra("completion_tokens")),
        "cost_usd": extra("cost_usd"),
        "cost_percent": 100 * extra("cost_usd") / cost_without if cost_without else None,
    }


def families_projection(sequential):
    """N families reading the book: everyone generates vs. generate once and share."""
    cost = sequential["cost_usd"]
    return {
        "families": config.FAMILIES,
        "without_shared_storage_usd": config.FAMILIES * cost,
        "with_shared_storage_usd": cost,  # the other families read from SQLite: no AI call, no AI cost
    }


def measure_reload(book_id, run_id):
    """A second family opens the same book: all questions come from SQLite, no AI call."""
    timings_ms = []
    for _ in range(config.RELOAD_READS):
        started = time.perf_counter()
        questions = actions.load_book_questions(book_id, run_id)
        timings_ms.append((time.perf_counter() - started) * 1000)
    return {
        "reads": len(timings_ms),
        "questions": len(questions),
        "avg_ms": statistics.mean(timings_ms),
        "min_ms": min(timings_ms),
        "max_ms": max(timings_ms),
    }


def stopped_by_budget(runs):
    return any(run and run["status"] == "budget_stop"
               for model_runs in runs.values() for run in (model_runs[SEQUENTIAL], model_runs[PARALLEL]))


def print_chapter(result):
    status = "ok" if result["ok"] else "FAILED - no valid JSON"
    print(f"  chapter {result['chapter_no']:>2}: {result['seconds']:5.1f} s, "
          f"{result['prompt_tokens']:>6,} in / {result['completion_tokens']:>5,} out tokens, "
          f"${result['cost_usd']:.4f}  {status}")


def secs(value):
    return "-" if value is None else f"{value:.1f} s"


def vendor_of(key):
    return key.split("-")[0]


def size_of(key):
    return key.split("-")[1]


def parse_args():
    parser = argparse.ArgumentParser(description="Speed and cost benchmark for AI-generated reading questions.")
    parser.add_argument("--model", choices=["big", "small", "both"], default="both",
                        help="model size(s) to run (default: both)")
    parser.add_argument("--vendor", choices=sorted({vendor_of(key) for key in config.MODELS}) + ["all"],
                        default="all", help="model vendor(s) to run (default: all)")
    parser.add_argument("--chapters", type=int, metavar="N", help="only the first N chapters (default: all)")
    args = parser.parse_args()
    if args.chapters is not None and args.chapters < 1:
        parser.error("--chapters must be at least 1")
    return args


if __name__ == "__main__":
    main()
