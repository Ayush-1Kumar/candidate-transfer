"""
Merger — combines PartialRecords from multiple sources into one CanonicalRecord.

Conflict resolution policy:
  - Scalar fields (name, headline, location): highest source_weight wins.
  - List fields (emails, phones, skills, experience, education): union with
    deduplication.  Skills: dedup by canonical name, confidence = max.
    Experience: dedup by normalised company + title + start date.
  - Provenance: union of all provenance entries (no duplicates).
  - Overall confidence: mean of per-field winner weights.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from candidate_transformer.models import (
    CanonicalRecord,
    EducationEntry,
    ExperienceEntry,
    PartialRecord,
    ProvenanceEntry,
    SkillEntry,
)


def _normalize_company(name: str) -> str:
    """Strip common legal suffixes so 'Infosys Ltd' and 'Infosys' match."""
    return re.sub(r"\s+(ltd|inc|corp|llc)\.?$", "", name.strip().lower(), flags=re.I)


def _pick_scalar(
    candidates: list[tuple[Any, float, str]],
) -> tuple[Any, ProvenanceEntry | None]:
    """
    Pick the best scalar value from a list of (value, weight, source) tuples.

    Winner: highest source_weight.  Ties broken lexicographically by value.
    Returns (None, None) when the candidate list is empty.
    """
    if not candidates:
        return None, None

    ranked = sorted(candidates, key=lambda x: (-x[1], str(x[0])))
    winner_value, winner_weight, winner_source = ranked[0]
    prov = ProvenanceEntry(
        field="",
        source=winner_source,
        method="merge_winner",
        confidence=winner_weight,
    )
    return winner_value, prov


def _merge_skills(partials: list[PartialRecord]) -> list[SkillEntry]:
    """
    Union skills across all partials.

    Deduplication key: canonical skill name.
    When the same skill appears in multiple sources, confidence = max and
    sources list is a union of all contributing sources.
    Output is sorted by confidence descending, then name ascending.
    """
    by_name: dict[str, SkillEntry] = {}
    for partial in partials:
        for skill in partial.skills:
            existing = by_name.get(skill.name)
            if not existing:
                by_name[skill.name] = SkillEntry(
                    name=skill.name,
                    confidence=skill.confidence,
                    sources=list(skill.sources),
                )
            else:
                existing.confidence = max(existing.confidence, skill.confidence)
                for src in skill.sources:
                    if src not in existing.sources:
                        existing.sources.append(src)
    return sorted(by_name.values(), key=lambda s: (-s.confidence, s.name))


def _merge_experience(partials: list[PartialRecord]) -> list[ExperienceEntry]:
    """
    Union experience entries across all partials.

    Deduplication key: normalised_company + title.lower() + start_date.
    When duplicates are found, richer data (summary, end date) is backfilled
    from secondary sources.  Output is sorted most-recent first.
    """
    seen: dict[str, ExperienceEntry] = {}
    for partial in partials:
        for exp in partial.experience:
            key = (
                f"{_normalize_company(exp.company)}"
                f"|{exp.title.lower()}"
                f"|{exp.start or ''}"
            )
            existing = seen.get(key)
            if not existing:
                seen[key] = exp
            else:
                # Backfill fields the first-seen entry was missing.
                if not existing.summary and exp.summary:
                    existing.summary = exp.summary
                if not existing.end and exp.end:
                    existing.end = exp.end
    return sorted(
        seen.values(),
        key=lambda e: (e.start or "0000-00", e.company),
        reverse=True,
    )


def _merge_education(partials: list[PartialRecord]) -> list[EducationEntry]:
    """
    Union education entries across all partials.

    Deduplication key: institution.lower() + degree + end_year.
    First-seen entry wins (ATS is loaded before CSV, so ATS data preferred).
    """
    seen: dict[str, EducationEntry] = {}
    for partial in partials:
        for edu in partial.education:
            key = (
                f"{edu.institution.lower()}"
                f"|{edu.degree or ''}"
                f"|{edu.end_year or ''}"
            )
            if key not in seen:
                seen[key] = edu
    return list(seen.values())


def merge_partials(partials: list[PartialRecord]) -> CanonicalRecord | None:
    """
    Merge a group of PartialRecords (all for the same candidate) into one
    canonical profile dict.

    Returns None if the input list is empty.
    """
    if not partials:
        return None

    # Candidate ID — take from the highest-weight source that has one.
    id_candidates = [(p.candidate_id, p.source_weight, p.source_name) for p in partials if p.candidate_id]
    candidate_id, _ = _pick_scalar(id_candidates)

    # Full name — highest-weight source wins.
    name_candidates = [(p.full_name, p.source_weight, p.source_name) for p in partials if p.full_name]
    full_name, _ = _pick_scalar(name_candidates)

    # Emails — union, sorted by source weight so the most trusted email is first.
    email_scores: dict[str, float] = {}
    for partial in partials:
        for email in partial.emails:
            email_scores[email] = max(email_scores.get(email, 0.0), partial.source_weight)
    emails = sorted(email_scores, key=lambda e: (-email_scores[e], e))

    # Phones — same union strategy as emails.
    phone_scores: dict[str, float] = {}
    for partial in partials:
        for phone in partial.phones:
            phone_scores[phone] = max(phone_scores.get(phone, 0.0), partial.source_weight)
    phones = sorted(phone_scores, key=lambda p: (-phone_scores[p], p))

    # Location — highest source_weight non-null dict wins.
    loc_candidates = [
        (p.location, p.source_weight, p.source_name)
        for p in partials
        if p.location
    ]
    location, _ = _pick_scalar(loc_candidates)

    # Links — for each named link key, pick from highest-weight source.
    links: dict[str, Any] = {
        "linkedin": None,
        "github": None,
        "portfolio": None,
        "other": [],
    }
    for link_key in ("linkedin", "github", "portfolio"):
        link_candidates = [
            (p.links.get(link_key), p.source_weight, p.source_name)
            for p in partials
            if p.links.get(link_key)
        ]
        links[link_key], _ = _pick_scalar(link_candidates)

    # Headline — highest-weight source wins.
    headline_candidates = [(p.headline, p.source_weight, p.source_name) for p in partials if p.headline]
    headline, _ = _pick_scalar(headline_candidates)

    # Years experience — convert to float after picking winner.
    years_candidates = [
        (p.years_experience, p.source_weight, p.source_name)
        for p in partials
        if p.years_experience is not None
    ]
    years_raw, _ = _pick_scalar(years_candidates)
    years_experience: float | None = float(years_raw) if years_raw is not None else None

    skills = _merge_skills(partials)
    experience = _merge_experience(partials)
    education = _merge_education(partials)

    # Provenance — union of all entries, deduped by (field, source, method).
    provenance: list[dict] = []
    seen_prov: set[tuple] = set()
    for partial in partials:
        for entry in partial.provenance:
            key = (entry.field, entry.source, entry.method)
            if key not in seen_prov:
                seen_prov.add(key)
                provenance.append(
                    {"field": entry.field, "source": entry.source, "method": entry.method}
                )

    # Overall confidence — mean of per-field winner weights.
    field_confidences: list[float] = []
    if full_name:
        field_confidences.append(max(p.source_weight for p in partials if p.full_name))
    if emails:
        field_confidences.append(max(email_scores.values()))
    if phones:
        field_confidences.append(max(phone_scores.values()))
    if skills:
        field_confidences.append(sum(s.confidence for s in skills) / len(skills))
    if experience:
        field_confidences.append(max(p.source_weight for p in partials if p.experience))

    overall_confidence = (
        round(sum(field_confidences) / len(field_confidences), 3)
        if field_confidences
        else 0.0
    )

    return {
        "candidate_id": candidate_id,
        "full_name": full_name,
        "emails": emails,
        "phones": phones,
        "location": location,
        "links": links,
        "headline": headline,
        "years_experience": years_experience,
        "skills": [
            {
                "name": s.name,
                "confidence": round(s.confidence, 3),
                "sources": s.sources,
            }
            for s in skills
        ],
        "experience": [
            {
                "company": e.company,
                "title": e.title,
                "start": e.start,
                "end": e.end,
                "summary": e.summary,
            }
            for e in experience
        ],
        "education": [
            {
                "institution": e.institution,
                "degree": e.degree,
                "field": e.field,
                "end_year": e.end_year,
            }
            for e in education
        ],
        "provenance": provenance,
        "overall_confidence": overall_confidence,
    }


def group_partials_by_candidate(
    partials: list[PartialRecord],
) -> dict[str, list[PartialRecord]]:
    """
    Group PartialRecords by candidate identity.

    Primary key: candidate_id.
    Fallback: primary email (for fragments that lack a candidate_id).
    Fragments with no identity signal are bucketed under a unique ephemeral
    key and filtered out in the pipeline layer.
    """
    groups: dict[str, list[PartialRecord]] = defaultdict(list)
    for partial in partials:
        key = (
            partial.candidate_id
            or (partial.emails[0] if partial.emails else None)
            or f"unknown_{id(partial)}"
        )
        groups[key].append(partial)
    return dict(groups)
