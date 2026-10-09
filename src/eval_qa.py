"""Evaluation harness for the grounded-Q&A acceptance criteria
(``4-grounded-qa-answer-sources-as-validated-structured-output-vision-capable-no-invented-citations``).

Runs N questions at temperature 0 through the full pipeline
(retrieve -> vision messages -> chat -> strict JSON schema + support
validation), audits every returned source (doc + page/slide + non-empty
excerpt overlapping the retrieved evidence, page/slide screenshot
availability), and writes per-question results plus a summary to
``outputs/findings/``.

Hermetic by design: ``retrieve_fn`` and ``chat_fn`` are injectable (the test
suite stubs both); the default path uses the real pipeline, which requires
the class endpoints from ``.env`` and a non-empty library.

Usage::

    python -m src.eval_qa                          # default eval set
    python -m src.eval_qa --list-defaults
    python -m src.eval_qa --questions "What is quantization?" "Explain RAG"
    python -m src.eval_qa --no-vision --out outputs/findings/my_eval.json
    python -m src.eval_qa --compare-rerank          # rerank ON vs OFF, same Qs

The default eval set follows the assignment spec: 5-10 questions covering
slide/syllabus text, at least two visual questions (including the Week 2
"Vibe Coding on Prod" meme), and at least one question the materials cannot
answer.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from src import config, qa

# --------------------------------------------------------------------------- #
# Eval set
# --------------------------------------------------------------------------- #
# Tailor to YOUR library (the app is generic - these probe topics the team's
# course decks cover). Follows the assignment spec: 5-10 questions, at least
# two visual questions (including the Week 2 "Vibe Coding on Prod" meme),
# and at least one question the materials cannot answer (honesty probe).
DEFAULT_EVAL_SET: list[str] = [
    # --- text-grounded factual (must cite doc + page + excerpt) ----------
    "What is quantization?",
    "What does fine-tuning do to a model's weights?",
    "What is a context window and why does it matter for RAG?",
    "How can a Gradio app be launched so that others can reach it?",
    # --- multi-source synthesis (must cite 2+ sources) --------------------
    "How do quantization and fine-tuning compare as ways to optimize an LLM?",
    "What are the main components of a retrieval-augmented generation system?",
    # --- vision path: assignment requires >=2 visual questions -------------
    "Find the meme about Vibe Coding on 'Prod' in the Week 2 slides and "
    "summarize what its image and text show.",
    "Describe the RAG pipeline as it is shown in the diagram.",
    # --- out-of-materials: assignment requires >=1 the materials can't answer
    "What is the capital of France?",
    # --- thin/ambiguous evidence probe ------------------------------------
    "How was this course assistant built?",
]

RESULTS_NAME = "grounded_qa_eval"
LATEST_NAME = f"{RESULTS_NAME}_latest.json"
COMPARE_NAME = "grounded_qa_compare_rerank"
COMPARE_LATEST_NAME = f"{COMPARE_NAME}_latest.json"


# --------------------------------------------------------------------------- #
# Source audit (acceptance criteria 2 + 4)
# --------------------------------------------------------------------------- #
def audit_sources(sources: list[dict], candidates: list) -> list[dict]:
    """Per-source audit: doc + page/slide + non-empty excerpt + evidence pin +
    page/slide screenshot availability + excerpt-overlap support check."""
    by_page = {(c.doc, c.page_no): c for c in candidates}
    audited: list[dict] = []
    for s in sources or []:
        if not isinstance(s, dict):
            audited.append({"schema_issue": "source not an object"})
            continue
        doc, page = s.get("doc"), s.get("page_no")
        excerpt = str(s.get("excerpt", ""))
        cand = by_page.get((doc, page))
        image_path = str(cand.image_path) if cand else str(s.get("image_path", ""))
        audited.append({
            "doc": doc,
            "page_no": page,
            "kind": cand.kind if cand else s.get("kind"),
            "doc_title": cand.doc_title if cand else s.get("doc_title"),
            "excerpt": excerpt,
            "excerpt_chars": len(excerpt),
            "excerpt_nonempty": bool(excerpt.strip()),
            "pinned_to_evidence": cand is not None,
            "page_screenshot_available": bool(image_path) and (
                config.PROJECT_ROOT / image_path).exists(),
            "image_path": image_path,
            "excerpt_overlaps_evidence": qa.excerpt_overlaps(excerpt, candidates),
        })
    return audited


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def run_eval(questions: list[str] | None = None,
             retrieve_fn=None, chat_fn=None,
             include_images: bool = True, temperature: float = 0.0,
             use_rerank: bool = True, out_path: str | Path | None = None,
             write_results: bool = True) -> dict:
    """Run the eval set and return the full payload (also written to disk).

    ``retrieve_fn(query, use_rerank=...) -> list[Candidate]`` and
    ``chat_fn(messages, **kwargs) -> str`` are injectable for hermetic tests;
    defaults use the real pipeline. ``write_results=False`` suppresses file
    output (used by ``compare_rerank``, which writes one combined file).
    """
    if retrieve_fn is None:
        from src.retrieve import retrieve as retrieve_fn
    questions = list(questions) if questions else list(DEFAULT_EVAL_SET)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records: list[dict] = []
    for q in questions:
        rec: dict = {"question": q, "retrieval_count": 0}
        t0 = time.time()
        try:
            candidates = retrieve_fn(q, use_rerank=use_rerank)
        except Exception as exc:  # noqa: BLE001 - recorded, never fatal
            rec.update({"conducted": False, "reason": f"retrieval error: {exc}"})
            records.append(rec)
            continue
        rec["retrieval_count"] = len(candidates)
        rec["retrieved"] = [
            {"doc": c.doc, "doc_title": c.doc_title, "page_no": c.page_no,
             "kind": c.kind, "image_path": c.image_path}
            for c in candidates
        ]
        if not candidates:
            rec.update({"conducted": False,
                        "reason": "no candidates retrieved (empty library or no match)"})
            records.append(rec)
            continue
        try:
            result = qa.answer_question(q, candidates, chat_fn=chat_fn,
                                        include_images=include_images,
                                        temperature=temperature)
            rec.update({
                "conducted": True,
                "answer": result["answer"],
                "raw": result["raw"],
                "valid": result["valid"],
                "validation_errors": result["validation_errors"],
                "sources": audit_sources(result["sources"], candidates),
                "ladder": result["ladder"],
                "images_sent": result["images_sent"],
                "temperature_used": result["temperature_used"],
            })
        except ValueError as exc:  # empty-response ladder exhausted (criterion 5)
            if isinstance(exc, qa.EmptyResponseError):
                ladder = exc.ladder
            else:
                ladder = {"rungs_used": 3, "retried": True,
                          "images_stripped": include_images}
            rec.update({
                "conducted": True,
                "answer": "",
                "raw": "",
                "valid": False,
                "validation_errors": [f"empty-response ladder exhausted: {exc}"],
                "sources": [],
                "ladder": ladder,
                "images_sent": 0,
            })
        rec["latency_s"] = round(time.time() - t0, 2)
        records.append(rec)

    payload = {
        "task": "4-grounded-qa-answer-sources-as-validated-structured-output-"
                "vision-capable-no-invented-citations",
        "run_at": now,
        "temperature": temperature,
        "include_images": include_images,
        "use_rerank": use_rerank,
        "n_questions": len(questions),
        "summary": _summarize(records),
        "results": records,
    }

    if write_results:
        if out_path is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            out_path = config.FINDINGS_DIR / f"{RESULTS_NAME}_{ts}.json"
            config.FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if out_path.name != LATEST_NAME:
            (out_path.parent / LATEST_NAME).write_text(
                json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _summarize(records: list[dict]) -> dict:
    answered = [r for r in records if r.get("conducted")]
    valid = [r for r in answered if r.get("valid")]
    returns = {
        "n_questions": len(records),
        "conducted": len(answered),
        "not_conducted": len(records) - len(answered),
        "schema_valid": len(valid),
        "valid_ratio": round(len(valid) / len(answered), 3) if answered else 0.0,
        "honest_refusals": sum(1 for r in answered
                               if r.get("answer") and qa.is_not_found(r["answer"])),
        "with_sources": sum(1 for r in answered if r.get("sources")),
        "vision_path_used": sum(1 for r in answered if (r.get("images_sent") or 0) > 0),
        "ladder_used": sum(1 for r in answered
                           if (r.get("ladder") or {}).get("retried")),
        "ladder_exhausted": sum(1 for r in answered if not r.get("valid")
                                and any("ladder exhausted" in e
                                        for e in (r.get("validation_errors") or []))),
        "failures": [
            {"question": r["question"],
             "errors": r.get("validation_errors") or [r.get("reason", "unknown")]}
            for r in answered if not r.get("valid")
        ] + [
            {"question": r["question"], "errors": [r.get("reason", "not conducted")]}
            for r in records if not r.get("conducted")
        ],
    }
    return returns


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_summary(summary: dict) -> None:
    print(f"\n=== Grounded QA eval: {summary['n_questions']} questions "
          f"({summary['conducted']} conducted) ===")
    print(f"  schema+support valid : {summary['schema_valid']}/{summary['conducted']} "
          f"({summary['valid_ratio'] * 100:.0f}%)")
    print(f"  honest refusals      : {summary['honest_refusals']} "
          f"(out-of-materials answered honestly)")
    print(f"  answers with sources : {summary['with_sources']}")
    print(f"  vision path used     : {summary['vision_path_used']} questions sent images")
    print(f"  fallback ladder used : {summary['ladder_used']} retries, "
          f"{summary['ladder_exhausted']} exhausted")
    if summary["failures"]:
        print("  FAILURES:")
        for f in summary["failures"]:
            print(f"    - {f['question'][:70]} -> {'; '.join(f['errors'])[:120]}")


def _cmp_row(rec: dict) -> dict:
    """Per-question comparison row: correctness(valid), support, timing."""
    return {
        "valid": rec.get("valid"),
        "validation_errors": rec.get("validation_errors") or [],
        "latency_s": rec.get("latency_s"),
        "n_sources": len(rec.get("sources") or []),
        "honest_refusal": bool(rec.get("answer") and qa.is_not_found(rec["answer"])),
        "retrieved_docs": sorted({r["doc"] for r in rec.get("retrieved", [])}),
    }


def compare_rerank(questions: list[str] | None = None,
                   retrieve_fn=None, chat_fn=None,
                   include_images: bool = True, temperature: float = 0.0,
                   out_path: str | Path | None = None) -> dict:
    """Assignment's design comparison: rerank ON vs OFF, SAME questions.

    Records per question whether the answer was schema+support valid, how
    many sources it cited, and how long it took (the assignment asks for
    correctness, source support, and timing). Answer *correctness* is a
    human judgment - review each answer against ground truth in the README.
    Saves one combined file to ``outputs/findings/``.
    """
    questions = list(questions) if questions else list(DEFAULT_EVAL_SET)
    rerank_on = run_eval(questions=questions, retrieve_fn=retrieve_fn,
                         chat_fn=chat_fn, include_images=include_images,
                         temperature=temperature, use_rerank=True,
                         write_results=False)
    rerank_off = run_eval(questions=questions, retrieve_fn=retrieve_fn,
                          chat_fn=chat_fn, include_images=include_images,
                          temperature=temperature, use_rerank=False,
                          write_results=False)
    rows = []
    for a, b in zip(rerank_on["results"], rerank_off["results"]):
        rows.append({
            "question": a["question"],
            "conducted": bool(a.get("conducted")) and bool(b.get("conducted")),
            "rerank_on": _cmp_row(a),
            "rerank_off": _cmp_row(b),
        })
    payload = {
        "task": "4-grounded-qa-answer-sources-as-validated-structured-output-"
                "vision-capable-no-invented-citations",
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_questions": len(questions),
        "temperature": temperature,
        "include_images": include_images,
        "rerank_on_summary": rerank_on["summary"],
        "rerank_off_summary": rerank_off["summary"],
        "notes": "valid = strict JSON schema + sources support the answer. "
                 "Answer correctness is judged manually against the source "
                 "materials (see README).",
        "comparison": rows,
    }
    if out_path is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = config.FINDINGS_DIR / f"{COMPARE_NAME}_{ts}.json"
        config.FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if out_path.name != COMPARE_LATEST_NAME:
        (out_path.parent / COMPARE_LATEST_NAME).write_text(
            json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _print_comparison(payload: dict) -> None:
    on, off = payload["rerank_on_summary"], payload["rerank_off_summary"]
    print(f"\n=== Rerank ON vs OFF comparison: {payload['n_questions']} questions ===")
    print(f"  {'question':<58} {'ON valid/λ(s)':>14} {'OFF valid/λ(s)':>14}")
    for row in payload["comparison"]:
        a, b = row["rerank_on"], row["rerank_off"]
        on_cell = f"{a['valid']}/{a['latency_s']}" if a["latency_s"] is not None else "-"
        off_cell = f"{b['valid']}/{b['latency_s']}" if b["latency_s"] is not None else "-"
        print(f"  {row['question'][:58]:<58} {on_cell:>14} {off_cell:>14}")
    print(f"\n  rerank ON : {on['schema_valid']}/{on['conducted']} valid, "
          f"avg {sum(r['rerank_on']['latency_s'] or 0 for r in payload['comparison'] if r['rerank_on']['latency_s'] is not None) / max(1, on['conducted']):.1f}s")
    print(f"  rerank OFF: {off['schema_valid']}/{off['conducted']} valid, "
          f"avg {sum(r['rerank_off']['latency_s'] or 0 for r in payload['comparison'] if r['rerank_off']['latency_s'] is not None) / max(1, off['conducted']):.1f}s")
    if on["failures"] or off["failures"]:
        print("  FAILURES:")
        for label, s in (("ON", on), ("OFF", off)):
            for f in s["failures"]:
                print(f"    [{label}] {f['question'][:60]} -> {'; '.join(f['errors'])[:100]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "Grounded QA eval harness").splitlines()[0]))
    ap.add_argument("--questions", nargs="*", default=None,
                    help="questions to run (default: DEFAULT_EVAL_SET)")
    ap.add_argument("--out", default=None, help="results file (default: "
                    "outputs/findings/grounded_qa_eval_<ts>.json + _latest.json)")
    ap.add_argument("--no-vision", action="store_true",
                    help="disable sending page/slide images to the model")
    ap.add_argument("--no-rerank", action="store_true",
                    help="disable the class reranker in retrieval")
    ap.add_argument("--compare-rerank", action="store_true",
                    help="run the eval set with rerank ON and OFF and save a "
                    "side-by-side comparison (assignment design comparison)")
    ap.add_argument("--list-defaults", action="store_true",
                    help="print the default eval set and exit")
    args = ap.parse_args(argv)

    if args.list_defaults:
        for i, q in enumerate(DEFAULT_EVAL_SET, start=1):
            print(f"{i:2}. {q}")
        return 0

    from src.retrieve import endpoint_ready
    if not endpoint_ready("chat"):
        print("chat endpoint not configured - copy .env.example to .env and set "
              "the class values (see README.md).", file=sys.stderr)
        return 2

    questions = args.questions or None
    if args.compare_rerank:
        if questions:
            print(f"Comparison eval set: {len(questions)} question(s)")
        else:
            print(f"Comparison eval set: default ({len(DEFAULT_EVAL_SET)} questions)")
        payload = compare_rerank(questions=questions,
                                 include_images=not args.no_vision,
                                 out_path=args.out)
        _print_comparison(payload)
        print(f"\nSaved: {args.out or (config.FINDINGS_DIR / COMPARE_LATEST_NAME)}")
        return 0

    if questions:
        print(f"Eval set: {len(questions)} question(s)")
    else:
        print(f"Eval set: default ({len(DEFAULT_EVAL_SET)} questions)")

    payload = run_eval(questions=questions,
                       include_images=not args.no_vision,
                       use_rerank=not args.no_rerank,
                       out_path=args.out)
    _print_summary(payload["summary"])
    print(f"\nSaved: {args.out or (config.FINDINGS_DIR / LATEST_NAME)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
