"""
Recruiter notes (.txt) parser.

Extracts structured signals from free-text recruiter notes using regex
heuristics.  Also triggers GitHub profile fetch when a GitHub URL is present.

Because notes are unstructured and written by humans, confidence is lower
than for structured sources.  The parser never invents values.
"""
from __future__ import annotations

import re
from pathlib import Path

from candidate_transformer.models import PartialRecord, ProvenanceEntry, SOURCE_WEIGHTS
from candidate_transformer.parsers.github_parser import parse_github_from_notes_url

_SOURCE = "recruiter_notes"
_WEIGHT = SOURCE_WEIGHTS[_SOURCE]

# Matches "CAND-001" style IDs (case-insensitive).
CANDIDATE_ID_RE = re.compile(r"CAND-\d+", re.I)

# Matches LinkedIn profile URLs.
LINKEDIN_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_%-]+/?", re.I
)

# Broad URL pattern; GitHub and LinkedIn URLs are explicitly excluded below.
PORTFOLIO_RE = re.compile(
    r"https?://[A-Za-z0-9._-]+\.[A-Za-z]{2,}(?:/[^\s]*)?", re.I
)

# Matches "4+ years experience" / "4.5 years of experience" patterns.
YEARS_EXP_RE = re.compile(
    r"(\d+(?:\.\d+)?)\+?\s*years?\s+(?:of\s+)?experience", re.I
)


def parse_recruiter_notes(path: Path, mock_dir: Path | None = None) -> PartialRecord | None:
    """
    Parse a recruiter notes text file into a PartialRecord.

    Args:
        path: Path to the .txt notes file.
        mock_dir: Directory containing GitHub mock JSON files for offline mode.

    Returns:
        PartialRecord with whatever signals could be extracted, or None if the
        file is empty or unreadable.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    if not text.strip():
        return None

    # Candidate ID — must appear in the text as "CAND-NNN".
    id_match = CANDIDATE_ID_RE.search(text)
    candidate_id = id_match.group(0).upper() if id_match else None

    partial = PartialRecord(
        candidate_id=candidate_id,
        source_name=_SOURCE,
        source_weight=_WEIGHT,
    )

    # LinkedIn URL
    linkedin_match = LINKEDIN_RE.search(text)
    if linkedin_match:
        partial.links["linkedin"] = linkedin_match.group(0).rstrip("/")

    # Portfolio URL — skip GitHub and LinkedIn matches.
    for url_match in PORTFOLIO_RE.finditer(text):
        url = url_match.group(0).rstrip("/")
        if "github.com" in url or "linkedin.com" in url:
            continue
        partial.links["portfolio"] = url
        break  # Take the first non-social URL as the portfolio.

    # Years of experience (lower confidence — recruiter's rough estimate).
    years_match = YEARS_EXP_RE.search(text)
    if years_match:
        partial.years_experience = float(years_match.group(1))

    # GitHub — fetch profile (or mock) and merge signals into this partial.
    github_partial = parse_github_from_notes_url(text, candidate_id, mock_dir)
    if github_partial:
        if github_partial.links.get("github"):
            partial.links["github"] = github_partial.links["github"]
        if github_partial.headline and not partial.headline:
            partial.headline = github_partial.headline
        partial.skills.extend(github_partial.skills)
        partial.provenance.extend(github_partial.provenance)

    # Provenance for fields extracted from notes.
    for field_name, value in [
        ("candidate_id", candidate_id),
        ("links.linkedin", partial.links.get("linkedin")),
        ("links.portfolio", partial.links.get("portfolio")),
        ("years_experience", partial.years_experience),
    ]:
        if value:
            partial.provenance.append(
                ProvenanceEntry(
                    field=field_name,
                    source=_SOURCE,
                    method="notes_regex",
                    # Notes are less reliable than structured sources.
                    confidence=_WEIGHT * 0.7,
                )
            )

    return partial
