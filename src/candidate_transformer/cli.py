#!/usr/bin/env python3
"""
Command-line interface for the candidate data transformer.

Usage examples
--------------
# Default canonical schema -> stdout
python -m candidate_transformer.cli \\
    --csv data/sample_inputs/recruiter_export.csv \\
    --ats data/sample_inputs/ats_candidates.json \\
    --notes-dir data/sample_inputs \\
    --mock-dir data/sample_inputs

# Custom projection config -> file
python -m candidate_transformer.cli \\
    --csv data/sample_inputs/recruiter_export.csv \\
    --ats data/sample_inputs/ats_candidates.json \\
    --notes-dir data/sample_inputs \\
    --mock-dir data/sample_inputs \\
    --config config/custom_output.json \\
    -o data/sample_outputs/custom_profiles.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from candidate_transformer.pipeline import run_pipeline, write_output


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="candidate-transformer",
        description="Multi-source candidate data transformer — Eightfold assignment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--csv",
        type=Path,
        metavar="FILE",
        help="Recruiter CSV export (columns: candidate_id, name, email, phone, "
             "current_company, title, location)",
    )
    parser.add_argument(
        "--ats",
        type=Path,
        metavar="FILE",
        help="ATS JSON blob (array of applicant objects with non-canonical field names)",
    )
    parser.add_argument(
        "--notes-dir",
        type=Path,
        metavar="DIR",
        help="Directory containing recruiter notes (.txt files)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        metavar="FILE",
        help="Runtime output projection config (JSON) — omit for default canonical schema",
    )
    parser.add_argument(
        "--mock-dir",
        type=Path,
        metavar="DIR",
        help="Directory containing GitHub mock JSON files (offline / deterministic mode)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        metavar="FILE",
        help="Write JSON output to FILE (default: stdout)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point.  Returns 0 on success, 1 on configuration error."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Require at least one source.
    if not any([args.csv, args.ats, args.notes_dir]):
        parser.error("Provide at least one source: --csv, --ats, or --notes-dir")

    output_config = None
    if args.config:
        try:
            with args.config.open(encoding="utf-8") as f:
                output_config = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Error reading config file: {exc}", file=sys.stderr)
            return 1

    # When --mock-dir is not set, default to the parent of notes-dir so that
    # github_mock_CAND-*.json files placed alongside notes files are found.
    mock_dir = args.mock_dir
    if mock_dir is None and args.notes_dir:
        mock_dir = args.notes_dir.parent

    records = run_pipeline(
        csv_path=args.csv,
        ats_path=args.ats,
        notes_dir=args.notes_dir,
        output_config=output_config,
        mock_dir=mock_dir,
    )

    if args.output:
        write_output(records, args.output)
        print(f"Wrote {len(records)} record(s) to {args.output}", file=sys.stderr)
    else:
        json.dump(records, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
