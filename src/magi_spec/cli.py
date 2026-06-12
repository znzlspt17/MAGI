"""Thin CLI for MAGI Spec Engine."""

from __future__ import annotations

import argparse
import sys

from magi_spec.core.config import MagiConfig
from magi_spec.core.errors import MagiError
from magi_spec.engine import MagiSpecEngine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="magi-spec")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="Generate an approval candidate spec.")
    input_group = generate.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", help="Path to a .md or .txt request file.")
    input_group.add_argument("--text", help="Direct user request text.")
    generate.add_argument("--output", required=True, help="Output directory.")
    generate.add_argument("--project", help="Read-only project folder context.")
    generate.add_argument("--web-search", choices=["auto", "on", "off"], default=None)
    generate.add_argument("--allow-command-execution", action="store_true")
    generate.add_argument("--config", help="YAML or JSON config file.")
    generate.add_argument("--overwrite", action="store_true", help="Allow overwriting an existing run.")
    generate.add_argument("--pipeline", choices=["v1", "v2"], default=None,
                          help="Pipeline version override (default: from config, usually v2).")

    approve = subparsers.add_parser("approve", help="Promote approval candidate to final spec.")
    approve.add_argument("output_dir")
    approve.add_argument("--config", help="YAML or JSON config file.")

    revise = subparsers.add_parser("revise", help="Revise a run with user feedback.")
    revise.add_argument("output_dir")
    revise.add_argument("--feedback", required=True)
    revise.add_argument("--config", help="YAML or JSON config file.")

    answer_cmd = subparsers.add_parser("answer", help="(v2) Inject answers to blocking questions.")
    answer_cmd.add_argument("output_dir")
    answer_cmd.add_argument("--answers", required=True,
                            help="JSON file with list of {question_id, question, answer} objects.")
    answer_cmd.add_argument("--config", help="YAML or JSON config file.")

    status = subparsers.add_parser("status", help="Show run status.")
    status.add_argument("output_dir")
    status.add_argument("--config", help="YAML or JSON config file.")
    return parser


def engine_from_args(args: argparse.Namespace) -> MagiSpecEngine:
    config = MagiConfig.from_file(args.config) if getattr(args, "config", None) else MagiConfig.default()
    # CLI --pipeline overrides config
    if getattr(args, "pipeline", None):
        config.pipeline_version = args.pipeline
    return MagiSpecEngine(config=config)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        engine = engine_from_args(args)
        if args.command == "generate":
            if args.input:
                result = engine.generate_from_file(
                    input_path=args.input,
                    output_dir=args.output,
                    project_dir=args.project,
                    web_search_mode=args.web_search,
                    allow_command_execution=args.allow_command_execution,
                    overwrite=args.overwrite,
                )
            else:
                result = engine.generate_from_text(
                    text=args.text,
                    output_dir=args.output,
                    project_dir=args.project,
                    web_search_mode=args.web_search,
                    allow_command_execution=args.allow_command_execution,
                    overwrite=args.overwrite,
                )
        elif args.command == "approve":
            result = engine.approve(args.output_dir)
        elif args.command == "revise":
            result = engine.revise(output_dir=args.output_dir, feedback_path=args.feedback)
        elif args.command == "answer":
            import json as _json
            answers_path = Path(args.answers)
            if not answers_path.exists():
                print(f"magi-spec: error: answers file not found: {args.answers}", file=sys.stderr)
                return 1
            answers = _json.loads(answers_path.read_text(encoding="utf-8"))
            result = engine.answer(args.output_dir, answers=answers)
        elif args.command == "status":
            result = engine.status(args.output_dir)
        else:
            parser.error(f"Unknown command: {args.command}")
            return 2
    except (MagiError, OSError, ValueError) as exc:
        print(f"magi-spec: error: {exc}", file=sys.stderr)
        return 1

    print(f"status: {result.status}")
    if result.approval_candidate_path:
        print(f"approval_candidate: {result.approval_candidate_path}")
    if result.final_spec_path:
        print(f"final_spec: {result.final_spec_path}")
    if result.critical_report_path:
        print(f"critical_report: {result.critical_report_path}")
    if result.questions_path:
        print(f"questions: {result.questions_path}")
    if result.state_path:
        print(f"state: {result.state_path}")
    if result.heartbeat_path:
        print(f"heartbeat: {result.heartbeat_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
