"""
Pipeline orchestrator.

Ties together all pipeline stages:
  load_sources  -> parse PartialRecords from each source
  group         -> group by candidate identity
  merge         -> produce one CanonicalRecord per candidate
  validate      -> assert schema correctness
  project       -> (optional) reshape to custom output schema
  emit          -> return list of dicts / write JSON file

Failures in individual candidates are isolated — one bad record does not
abort the run.  Unknown candidates (no identity signal) are silently skipped.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from candidate_transformer.merger import group_partials_by_candidate, merge_partials
from candidate_transformer.models import PartialRecord
from candidate_transformer.parsers.ats_parser import parse_ats_json
from candidate_transformer.parsers.csv_parser import parse_recruiter_csv
from candidate_transformer.parsers.notes_parser import parse_recruiter_notes
from candidate_transformer.projector import project_record
from candidate_transformer.validator import validate_canonical

log = logging.getLogger(__name__)


def _empty_location() -> dict[str, None]:
    """Return a blank location dict that satisfies the canonical schema."""
    return {"city": None, "region": None, "country": None}


def _empty_links() -> dict[str, Any]:
    """Return a blank links dict that satisfies the canonical schema."""
    return {"linkedin": None, "github": None, "portfolio": None, "other": []}


def _ensure_defaults(record: dict[str, Any]) -> dict[str, Any]:
    """
    Back-fill any optional top-level keys that the merger may have omitted
    when no source provided a value for them.
    """
    record.setdefault("location", _empty_location())
    record.setdefault("links", _empty_links())
    record.setdefault("headline", None)
    record.setdefault("years_experience", None)
    record.setdefault("skills", [])
    record.setdefault("experience", [])
    record.setdefault("education", [])
    record.setdefault("provenance", [])
    record.setdefault("overall_confidence", 0.0)
    return record


def load_sources(
    csv_path: Path | None,
    ats_path: Path | None,
    notes_dir: Path | None,
    mock_dir: Path | None = None,
) -> list[PartialRecord]:
    """
    Parse all configured input sources and return a flat list of PartialRecords.

    Each source is parsed independently; failures in one source do not prevent
    other sources from being loaded.

    Args:
        csv_path:  Path to a recruiter CSV export, or None to skip.
        ats_path:  Path to an ATS JSON file, or None to skip.
        notes_dir: Directory containing recruiter notes (.txt), or None to skip.
        mock_dir:  Directory with GitHub mock JSONs for offline mode.

    Returns:
        List of PartialRecord instances from all sources combined.
    """
    partials: list[PartialRecord] = []

    if csv_path and csv_path.exists():
        try:
            partials.extend(parse_recruiter_csv(csv_path))
            log.debug("Loaded CSV: %s", csv_path)
        except Exception as exc:
            log.warning("Failed to parse CSV %s: %s", csv_path, exc)

    if ats_path and ats_path.exists():
        try:
            partials.extend(parse_ats_json(ats_path))
            log.debug("Loaded ATS JSON: %s", ats_path)
        except Exception as exc:
            log.warning("Failed to parse ATS JSON %s: %s", ats_path, exc)

    if notes_dir and notes_dir.exists():
        for notes_file in sorted(notes_dir.glob("*.txt")):
            try:
                parsed = parse_recruiter_notes(notes_file, mock_dir or notes_dir.parent)
                if parsed:
                    partials.append(parsed)
                    log.debug("Loaded notes: %s", notes_file)
            except Exception as exc:
                log.warning("Failed to parse notes %s: %s", notes_file, exc)

    return partials


def run_pipeline(
    csv_path: Path | None,
    ats_path: Path | None,
    notes_dir: Path | None,
    output_config: dict[str, Any] | None = None,
    mock_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """
    Run the full candidate transformation pipeline end-to-end.

    Args:
        csv_path:      Path to recruiter CSV, or None.
        ats_path:      Path to ATS JSON, or None.
        notes_dir:     Directory with recruiter notes, or None.
        output_config: Runtime projection config dict, or None for default schema.
        mock_dir:      GitHub mock directory for deterministic offline runs.

    Returns:
        List of canonical (or projected) profile dicts, one per candidate.
        Candidates that fail validation are silently excluded.
    """
    partials = load_sources(csv_path, ats_path, notes_dir, mock_dir)
    groups = group_partials_by_candidate(partials)

    results: list[dict[str, Any]] = []

    for group_key, group in sorted(groups.items()):
        # Skip records that had no identity signal — they can't be reliably matched.
        if group_key.startswith("unknown_"):
            log.debug("Skipping unidentified record group: %s", group_key)
            continue

        try:
            merged = merge_partials(group)
            if not merged:
                continue

            merged = _ensure_defaults(merged)
            validate_canonical(merged)

            output = project_record(merged, output_config) if output_config else merged
            results.append(output)

        except Exception as exc:
            # Isolate per-candidate failures — log and continue.
            log.warning("Skipping candidate %s: %s", group_key, exc)

    return results


def write_output(records: list[dict[str, Any]], path: Path) -> None:
    """
    Serialise *records* to a pretty-printed JSON file at *path*.

    Parent directories are created if they do not exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
        f.write("\n")
