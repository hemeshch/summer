"""CLI for the context engine.

Subcommands:
    seed     — load a curated set of demo facts so the rest of the pipeline
               has something to retrieve before real ingestion has happened.
    ingest   — run one ingestion pass over all configured sources.
    recall   — query the fact store and print the top matches.
    facts    — list everything in the store.
    stats    — print store stats.

Examples:
    python -m io_system.context_engine seed
    python -m io_system.context_engine ingest \\
        --conversation-log conversation_log.jsonl
    python -m io_system.context_engine recall "what does the user do at 2am"
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .embedder import build_default_embedder
from .engine import ContextEngine
from .extractor import FactExtractor
from .fact_store import Fact, FactStore
from .sources.base import DataSource
from .sources.calendar import AppleCalendarSource
from .sources.conversation import ConversationLogSource
from .sources.email import EmailSource


DEFAULT_DB = "context_facts.db"


# ----- demo seed data -----

DEMO_FACTS: List[Fact] = [
    Fact(
        text="User typically orders a matcha latte from Agora Coffee via DoorDash around 2am during late-night work sessions in the library.",
        kind="pattern",
        confidence=0.88,
        source_refs=["seed:agora_matcha_pattern"],
    ),
    Fact(
        text="User does deep work sessions from 10pm to 3am, usually 2–3 times per week.",
        kind="pattern",
        confidence=0.85,
        source_refs=["seed:deep_work_schedule"],
    ),
    Fact(
        text="User is taking COMP 326 at Rice this semester.",
        kind="fact",
        confidence=0.92,
        source_refs=["seed:enrolled_classes"],
    ),
    Fact(
        text="User studies in Fondren Library at night.",
        kind="pattern",
        confidence=0.8,
        source_refs=["seed:study_location"],
    ),
    Fact(
        text="User prefers short, warm, friendly texts — not formal or essay-length responses.",
        kind="preference",
        confidence=0.95,
        source_refs=["seed:tone_preference"],
    ),
    Fact(
        text="User's roommate's name is Michel; they often grab dinner together.",
        kind="fact",
        confidence=0.85,
        source_refs=["seed:relationships"],
    ),
    Fact(
        text="User is building a startup called Summer and applied to YC W26.",
        kind="fact",
        confidence=0.9,
        source_refs=["seed:current_project"],
    ),
    Fact(
        text="User responds well to playful nudges that reference shared context (e.g. 'damn it's 2am 💀').",
        kind="preference",
        confidence=0.78,
        source_refs=["seed:engagement_style"],
    ),
]


# ----- helpers -----

def _build_store(db_path: str) -> FactStore:
    embedder = build_default_embedder()
    return FactStore(db_path=db_path, embedder=embedder)


def _build_engine(
    db_path: str,
    conversation_log: Optional[str],
    email_fixture: Optional[str],
    enable_calendar: bool,
) -> ContextEngine:
    sources: List[DataSource] = []
    if conversation_log:
        sources.append(ConversationLogSource(log_path=conversation_log))
    if email_fixture:
        sources.append(EmailSource(fixture_path=email_fixture))
    if enable_calendar:
        sources.append(AppleCalendarSource())
    return ContextEngine(
        sources=sources,
        extractor=FactExtractor(),
        store=_build_store(db_path),
    )


# ----- subcommands -----

def cmd_seed(args) -> int:
    store = _build_store(args.db)
    print(f"Seeding {len(DEMO_FACTS)} demo facts into {args.db} ...")
    store.add_many(DEMO_FACTS)
    print(f"Done. Total facts in store: {store.count()}")
    return 0


def cmd_ingest(args) -> int:
    engine = _build_engine(
        db_path=args.db,
        conversation_log=args.conversation_log,
        email_fixture=args.email_fixture,
        enable_calendar=args.calendar,
    )
    if not engine.sources:
        print("No sources configured. Pass --conversation-log / --email-fixture / --calendar.",
              file=sys.stderr)
        return 2
    since = None
    if args.since:
        since = datetime.fromisoformat(args.since)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
    report = engine.run_daily_ingest(since=since)
    print(report.summary())
    if args.verbose and report.extractor_raw_response:
        print("\n--- extractor raw response ---")
        print(report.extractor_raw_response)
    return 0


def cmd_recall(args) -> int:
    store = _build_store(args.db)
    results = store.search(args.query, top_k=args.top_k)
    if not results:
        print("(no matches)")
        return 0
    for f in results:
        print(f"  {f.score:.3f}  [{f.kind:>10}]  {f.text}")
        if args.show_sources and f.source_refs:
            print(f"             sources: {', '.join(f.source_refs)}")
    return 0


def cmd_facts(args) -> int:
    store = _build_store(args.db)
    facts = store.all_facts()
    print(f"{len(facts)} facts in {args.db}\n")
    for f in facts:
        print(f"  #{f.id} [{f.kind}] conf={f.confidence:.2f}  {f.text}")
        if args.show_sources and f.source_refs:
            print(f"      sources: {', '.join(f.source_refs)}")
    return 0


def cmd_stats(args) -> int:
    store = _build_store(args.db)
    facts = store.all_facts()
    by_kind: dict = {}
    for f in facts:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    print(f"DB: {args.db}")
    print(f"Total facts: {len(facts)}")
    for k, v in sorted(by_kind.items()):
        print(f"  {k}: {v}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="context_engine", description=__doc__)
    p.add_argument("--db", default=os.environ.get("SUMMER_FACT_DB", DEFAULT_DB),
                   help="Path to the fact store sqlite file")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="Load demo facts")
    s.set_defaults(func=cmd_seed)

    s = sub.add_parser("ingest", help="Run one ingestion pass")
    s.add_argument("--conversation-log", default=None,
                   help="Path to a JSONL conversation log")
    s.add_argument("--email-fixture", default=None,
                   help="Path to a JSONL email fixture")
    s.add_argument("--calendar", action="store_true",
                   help="Pull events from Apple Calendar via Shortcuts")
    s.add_argument("--since", default=None,
                   help="ISO timestamp; overrides state file high-water mark")
    s.add_argument("--verbose", "-v", action="store_true")
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("recall", help="Semantic query against the store")
    s.add_argument("query")
    s.add_argument("--top-k", "-k", type=int, default=5)
    s.add_argument("--show-sources", action="store_true")
    s.set_defaults(func=cmd_recall)

    s = sub.add_parser("facts", help="List all facts")
    s.add_argument("--show-sources", action="store_true")
    s.set_defaults(func=cmd_facts)

    s = sub.add_parser("stats", help="Print store stats")
    s.set_defaults(func=cmd_stats)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
