"""
ATS (Applicant Tracking System) JSON parser.

The ATS uses its own field names that do NOT match the canonical schema
(e.g. "applicant_ref" instead of "candidate_id", "fullName" instead of
"full_name").  This parser handles that mapping explicitly.

Expected JSON structure: a top-level array of applicant objects.
"""
from __future__ import annotations

import json
from pathlib import Path

from candidate_transformer.models import (
    EducationEntry,
    ExperienceEntry,
    PartialRecord,
    ProvenanceEntry,
    SkillEntry,
    SOURCE_WEIGHTS,
)
from candidate_transformer.normalizers.phone import normalize_phone_e164
from candidate_transformer.normalizers.skills import canonicalize_skill
from candidate_transformer.normalizers.text import (
    normalize_date,
    normalize_email,
    normalize_name,
    years_between,
)

_SOURCE = "ats_json"
_WEIGHT = SOURCE_WEIGHTS[_SOURCE]


def parse_ats_json(path: Path) -> list[PartialRecord]:
    """
    Parse an ATS JSON blob into a list of PartialRecords.

    The ATS schema uses non-canonical field names; the mapping is handled
    here so that no downstream code needs to know about ATS internals.

    Args:
        path: Absolute path to the JSON file.

    Returns:
        List of PartialRecord instances, one per applicant object.

    Raises:
        OSError: If the file cannot be opened.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    records: list[PartialRecord] = []

    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    # Tolerate a single-object file by wrapping it.
    if isinstance(data, dict):
        data = [data]

    if not isinstance(data, list):
        return records

    for item in data:
        if not isinstance(item, dict):
            continue

        contact = item.get("contact") or {}
        candidate_id = str(item.get("applicant_ref") or "").strip() or None
        name = normalize_name(contact.get("fullName"))
        email = normalize_email(contact.get("emailAddress"))
        # ATS data is predominantly Indian — use IN as default region.
        phone = normalize_phone_e164(contact.get("mobile"), default_region="IN")

        partial = PartialRecord(
            candidate_id=candidate_id,
            full_name=name,
            emails=[email] if email else [],
            phones=[phone] if phone else [],
            source_name=_SOURCE,
            source_weight=_WEIGHT,
        )

        # Skills: ATS stores a flat list; canonicalize each entry.
        for skill_name in item.get("skills_list") or []:
            canonical = canonicalize_skill(str(skill_name))
            if canonical:
                partial.skills.append(
                    SkillEntry(
                        name=canonical,
                        confidence=_WEIGHT * 0.9,
                        sources=[_SOURCE],
                    )
                )

        # Work history
        for work in item.get("work_history") or []:
            if not isinstance(work, dict):
                continue
            partial.experience.append(
                ExperienceEntry(
                    company=str(work.get("org") or "").strip(),
                    title=str(work.get("role") or "").strip(),
                    start=normalize_date(work.get("from")),
                    end=normalize_date(work.get("to")),
                    summary=(work.get("description") or None),
                )
            )

        # Education history
        for edu in item.get("education_history") or []:
            if not isinstance(edu, dict):
                continue
            end_year_raw = edu.get("graduated")
            partial.education.append(
                EducationEntry(
                    institution=str(edu.get("school") or "").strip(),
                    degree=(edu.get("qualification") or None),
                    field=(edu.get("major") or None),
                    end_year=int(end_year_raw) if end_year_raw else None,
                )
            )

        # Derive headline from currentRole block.
        current = item.get("currentRole") or {}
        if current.get("employer") and current.get("positionTitle"):
            partial.headline = f"{current['positionTitle']} at {current['employer']}"

        # Derive total experience from the earliest start date in work history.
        if partial.experience:
            earliest_start = min(
                (e.start for e in partial.experience if e.start),
                default=None,
            )
            if earliest_start:
                partial.years_experience = years_between(earliest_start)

        # Record provenance for every populated field.
        for field_name, value in [
            ("candidate_id", candidate_id),
            ("full_name", name),
            ("emails", email),
            ("phones", phone),
            ("skills", partial.skills),
            ("experience", partial.experience),
            ("education", partial.education),
            ("headline", partial.headline),
            ("years_experience", partial.years_experience),
        ]:
            if value:
                partial.provenance.append(
                    ProvenanceEntry(
                        field=field_name,
                        source=_SOURCE,
                        method="ats_json_field",
                        confidence=_WEIGHT,
                    )
                )

        records.append(partial)

    return records
