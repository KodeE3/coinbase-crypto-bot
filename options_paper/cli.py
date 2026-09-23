"""Run with: python -m options_paper.cli --demo"""

import argparse
import json
from pathlib import Path
from .engine import propose, record_approval


def main():
    parser = argparse.ArgumentParser(description="Educational paper-only options proposal")
    parser.add_argument("--demo", action="store_true", help="use the dated, fictional sample snapshot")
    parser.add_argument("--snapshot", type=Path, help="JSON snapshot of daily closes and options quotes")
    parser.add_argument("--journal", type=Path, default=Path("options_paper_journal.jsonl"))
    args = parser.parse_args()
    if args.demo == bool(args.snapshot):
        parser.error("Choose exactly one of --demo or --snapshot")
    source = Path(__file__).with_name("sample_snapshot.json") if args.demo else args.snapshot
    snapshot = json.loads(source.read_text(encoding="utf-8"))
    result = propose(snapshot, demo=args.demo)
    print(json.dumps(result, indent=2))
    if "rejected" in result:
        return
    print("SIMULATION ONLY: type the full contract symbol to record an illustrative buy; Enter skips.")
    typed = input("Contract: ").strip()
    if not typed:
        print("Skipped; no journal entry created.")
        return
    event = record_approval(result, args.journal, typed)
    print("Recorded simulated buy:", json.dumps(event))


if __name__ == "__main__":
    main()
