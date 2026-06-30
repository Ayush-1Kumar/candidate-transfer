"""
Core data models shared across all pipeline stages.

PartialRecord  — raw fragment extracted from one source before merging.
CanonicalRecord — the final merged profile dict (matches the output schema).
SOURCE_WEIGHTS  — trust scores used during conflict resolution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProvenanceEntry:
    """Tracks where a specific field value came from."""

    field: str
    source: str      # e.g. "ats_json", "recruiter_csv"
    method: str      # e.g. "csv_column", "github_api"
    confidence: float = 0.0


@dataclass
class SkillEntry:
    """A single skill with its merged confidence score and contributing sources."""

    name: str
    confidence: float
    sources: list[str] = field(default_factory=list)


@dataclass
class ExperienceEntry:
    """One employment record."""

    company: str
    title: str
    start: str | None   # YYYY-MM or None
    end: str | None     # YYYY-MM or None; None means current role
    summary: str | None = None


@dataclass
class EducationEntry:
    """One education record."""

    institution: str
    degree: str | None
    field: str | None
    end_year: int | None


@dataclass
class PartialRecord:
    """
    Raw fragment extracted from a single source before merging.

    Multiple PartialRecords for the same candidate are merged by the
    merger module into a single CanonicalRecord.
    """

    candidate_id: str | None = None
    full_name: str | None = None
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    location: dict[str, str | None] | None = None
    links: dict[str, Any] = field(default_factory=dict)
    headline: str | None = None
    years_experience: float | None = None
    skills: list[SkillEntry] = field(default_factory=list)
    experience: list[ExperienceEntry] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    provenance: list[ProvenanceEntry] = field(default_factory=list)

    # Metadata — not emitted in output; used only during merge.
    source_name: str = ""
    source_weight: float = 0.5


# Type alias for the final merged profile dict.
CanonicalRecord = dict[str, Any]

# Trust weights assigned to each source type.
# Higher weight = preferred winner when values conflict.
SOURCE_WEIGHTS: dict[str, float] = {
    "recruiter_csv": 0.85,
    "ats_json": 0.90,
    "github": 0.70,
    "recruiter_notes": 0.55,
}
