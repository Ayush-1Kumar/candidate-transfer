"""
Projection layer — reshapes a canonical profile into a custom output schema.

The canonical record is kept intact internally.  A JSON config provided at
runtime controls what the final output looks like: which fields to include,
how to rename or remap them, what normalisation to apply, and what to do when
a value is missing.

This design keeps a clean separation between the engine (merger + validator)
and the presentation layer (projector).
"""
from __future__ import annotations

import re
from typing import Any

from candidate_transformer.normalizers.phone import normalize_phone_e164
from candidate_transformer.normalizers.skills import canonicalize_skill, canonicalize_skills


class ProjectionError(Exception):
    """Raised when a required field is missing or a type assertion fails."""


def _get_path_value(record: dict[str, Any], path: str) -> Any:
    """
    Resolve a field path from a canonical record dict.

    Supported path syntax:
      - Simple key:        "full_name"
      - Nested key:        "links.github"
      - Indexed array:     "emails[0]"
      - Array projection:  "skills[].name"  -> list of name values

    Returns None when the path resolves to nothing.
    """
    if not path:
        return record

    # "skills[].name" — collect a sub-field from every array element.
    array_proj = re.match(r"^(\w+)\[\]\.(\w+)$", path)
    if array_proj:
        array_key, sub_key = array_proj.groups()
        items = record.get(array_key) or []
        if not isinstance(items, list):
            return None
        return [
            item.get(sub_key)
            for item in items
            if isinstance(item, dict) and item.get(sub_key) is not None
        ]

    # "emails[0]" — single element from an array.
    index_access = re.match(r"^(\w+)\[(\d+)\]$", path)
    if index_access:
        key, idx = index_access.groups()
        items = record.get(key)
        if not isinstance(items, list):
            return None
        i = int(idx)
        return items[i] if 0 <= i < len(items) else None

    # "links.github" — dotted nested access.
    if "." in path:
        current: Any = record
        for part in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    return record.get(path)


def _apply_normalize(value: Any, normalize: str | None) -> Any:
    """
    Apply a named normalisation function to a projected value.

    Supported normalise directives:
      "E164"      — parse phone string to E.164 format.
      "canonical" — canonicalize skill name(s).
    Unknown directives are silently ignored (value returned as-is).
    """
    if normalize is None or value is None:
        return value

    if normalize == "E164":
        return normalize_phone_e164(value) if isinstance(value, str) else value

    if normalize == "canonical":
        if isinstance(value, list):
            return canonicalize_skills([str(v) for v in value])
        if isinstance(value, str):
            return canonicalize_skill(value)
        return value

    return value


def _validate_type(value: Any, expected_type: str) -> bool:
    """Return True when *value* matches *expected_type*, or when value is None."""
    if value is None:
        return True
    type_checks: dict[str, type | tuple] = {
        "string": str,
        "number": (int, float),
        "string[]": list,
        "object": dict,
    }
    checker = type_checks.get(expected_type)
    if checker is None:
        return True  # Unknown type — accept anything.
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "string[]":
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    return isinstance(value, checker)


def project_record(canonical: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """
    Project a canonical record to a custom output schema defined by *config*.

    Config schema:
      fields           list of field descriptors (see below)
      include_confidence  bool — append overall_confidence to output
      include_provenance  bool — append provenance list to output
      on_missing       "null" | "omit" | "error"

    Field descriptor keys:
      path      str  output key name (required)
      from      str  source path in canonical record (defaults to path)
      type      str  expected output type for validation
      required  bool raise/omit/null when missing (governed by on_missing)
      normalize str  "E164" or "canonical"

    Raises:
        ProjectionError: When on_missing="error" and a required field is absent,
                         or when a value fails the type assertion.
    """
    fields: list[dict] = config.get("fields") or []
    on_missing: str = config.get("on_missing", "null")
    include_confidence: bool = config.get("include_confidence", False)
    include_provenance: bool = config.get("include_provenance", False)

    output: dict[str, Any] = {}

    for field_def in fields:
        path = field_def.get("path")
        if not path:
            continue  # Skip malformed field descriptors.

        source_path = field_def.get("from", path)
        value = _get_path_value(canonical, source_path)
        value = _apply_normalize(value, field_def.get("normalize"))

        required: bool = field_def.get("required", False)
        expected_type: str = field_def.get("type", "string")

        # Handle missing / empty values.
        if value is None or value == "" or value == []:
            if required and on_missing == "error":
                raise ProjectionError(f"Required field missing: {path}")
            if on_missing == "omit":
                continue
            value = None  # Emit null for "null" policy.

        # Type assertion — catch schema mismatches early.
        if value is not None and not _validate_type(value, expected_type):
            raise ProjectionError(
                f"Field '{path}' expected type '{expected_type}', "
                f"got '{type(value).__name__}'"
            )

        output[path] = value

    if include_confidence:
        output["overall_confidence"] = canonical.get("overall_confidence")

    if include_provenance:
        output["provenance"] = canonical.get("provenance")

    return output
