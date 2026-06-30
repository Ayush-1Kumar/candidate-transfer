"""
Canonical record validator.

Validates that a merged profile dict conforms to the canonical schema before
it leaves the pipeline.  Uses structural checks rather than a JSON-Schema
library to keep dependencies minimal and error messages human-readable.

Design principle: the validator is intentionally strict about *shape* but
lenient about *content* — e.g. it checks that phones is a list, not that
every element is a valid E.164 string (normalisation already handled that).
"""
from __future__ import annotations

from typing import Any

# Every canonical profile must contain exactly these top-level keys.
REQUIRED_DEFAULT_FIELDS: frozenset[str] = frozenset({
    "candidate_id",
    "full_name",
    "emails",
    "phones",
    "location",
    "links",
    "headline",
    "years_experience",
    "skills",
    "experience",
    "education",
    "provenance",
    "overall_confidence",
})


class ValidationError(Exception):
    """Raised when a canonical record violates the schema contract."""


def validate_canonical(record: dict[str, Any]) -> None:
    """
    Assert that *record* is a valid canonical profile.

    Checks:
      - All required top-level keys are present.
      - Types of scalar fields (candidate_id, full_name, years_experience).
      - Structure of complex fields (location, links, skills, experience, education, provenance).
      - Date format (YYYY-MM) on experience start/end.
      - Provenance entries have field / source / method keys.

    Raises:
        ValidationError: On the first schema violation found.
    """
    missing = REQUIRED_DEFAULT_FIELDS - set(record.keys())
    if missing:
        raise ValidationError(f"Missing required fields: {sorted(missing)}")

    # Scalar type checks
    _check_string_or_null(record, "candidate_id")
    _check_string_or_null(record, "full_name")

    for list_field in ("emails", "phones"):
        val = record.get(list_field)
        if val is not None and not isinstance(val, list):
            raise ValidationError(f"'{list_field}' must be a list or null")

    _validate_location(record.get("location"))
    _validate_links(record.get("links"))

    years = record.get("years_experience")
    if years is not None and not isinstance(years, (int, float)):
        raise ValidationError("'years_experience' must be a number or null")

    _validate_skills(record.get("skills"))
    _validate_experience(record.get("experience"))
    _validate_provenance(record.get("provenance"))

    confidence = record.get("overall_confidence")
    if confidence is not None and not isinstance(confidence, (int, float)):
        raise ValidationError("'overall_confidence' must be a number")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _check_string_or_null(record: dict[str, Any], key: str) -> None:
    val = record.get(key)
    if val is not None and not isinstance(val, str):
        raise ValidationError(f"'{key}' must be a string or null")


def _validate_location(location: Any) -> None:
    if location is None:
        return
    if not isinstance(location, dict):
        raise ValidationError("'location' must be an object or null")
    for key in ("city", "region", "country"):
        val = location.get(key)
        if val is not None and not isinstance(val, str):
            raise ValidationError(f"'location.{key}' must be a string or null")


def _validate_links(links: Any) -> None:
    if links is None:
        return
    if not isinstance(links, dict):
        raise ValidationError("'links' must be an object")
    for key in ("linkedin", "github", "portfolio"):
        val = links.get(key)
        if val is not None and not isinstance(val, str):
            raise ValidationError(f"'links.{key}' must be a string or null")
    if "other" in links and not isinstance(links["other"], list):
        raise ValidationError("'links.other' must be a list")


def _validate_skills(skills: Any) -> None:
    if skills is None:
        return
    if not isinstance(skills, list):
        raise ValidationError("'skills' must be a list")
    for skill in skills:
        if not isinstance(skill, dict) or "name" not in skill:
            raise ValidationError("Each skill entry must be an object with a 'name' key")


def _validate_experience(experience: Any) -> None:
    if experience is None:
        return
    if not isinstance(experience, list):
        raise ValidationError("'experience' must be a list")
    for exp in experience:
        if not isinstance(exp, dict):
            raise ValidationError("Each experience entry must be an object")
        for date_field in ("start", "end"):
            val = exp.get(date_field)
            if val is not None and (
                not isinstance(val, str)
                or len(val) != 7
                or val[4] != "-"
            ):
                raise ValidationError(
                    f"experience.{date_field} must be YYYY-MM format or null, got: {val!r}"
                )


def _validate_provenance(provenance: Any) -> None:
    if provenance is None:
        return
    if not isinstance(provenance, list):
        raise ValidationError("'provenance' must be a list")
    for entry in provenance:
        if not isinstance(entry, dict):
            raise ValidationError("Each provenance entry must be an object")
        for key in ("field", "source", "method"):
            if key not in entry:
                raise ValidationError(f"Provenance entry missing required key '{key}'")
