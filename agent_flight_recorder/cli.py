"""Command-line interface: ``afr audit traces.jsonl --policy policy.json``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .audit import audit_runs
from .report import render_html
from .trace import TraceError, load_runs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="afr", description="Audit AI-agent traces against a policy.")
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit", help="audit a JSONL trace file")
    audit.add_argument("traces", type=Path)
    audit.add_argument("--policy", type=Path, required=True)
    audit.add_argument("--html", type=Path, help="write a self-contained HTML report")
    audit.add_argument("--json", type=Path, dest="json_path", help="write machine-readable results")
    audit.add_argument("--pass-score", type=int, default=80, help="minimum score for a run to pass")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Return 0 if all runs pass, 1 if any run fails, 2 on unusable input."""
    args = build_parser().parse_args(argv)
    try:
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        runs = load_runs(args.traces)
    except (OSError, json.JSONDecodeError, TraceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    results = audit_runs(runs, policy, args.pass_score)
    for result in results:
        label = "PASS" if result.passed else "FAIL"
        print(f"{label}  {result.score:>3}  {result.run.run_id}  ({len(result.findings)} findings)")
        for finding in result.findings:
            step = f"step {finding.step}" if finding.step is not None else "run"
            print(f"      [{finding.severity}] {step}: {finding.message}")

    if args.html:
        args.html.write_text(render_html(results), encoding="utf-8")
    if args.json_path:
        args.json_path.write_text(json.dumps([result.to_dict() for result in results], indent=2), encoding="utf-8")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
