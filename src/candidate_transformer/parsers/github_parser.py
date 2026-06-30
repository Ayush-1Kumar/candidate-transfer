"""
GitHub profile parser.

Supports two modes:
  - Offline / deterministic: reads a pre-saved mock JSON file.
  - Live: fetches from the public GitHub REST API (no auth required for public
    profiles; rate-limited to 60 req/hour unauthenticated).

Skills are inferred from the programming languages used across public repos.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

from candidate_transformer.models import (
    PartialRecord,
    ProvenanceEntry,
    SkillEntry,
    SOURCE_WEIGHTS,
)
from candidate_transformer.normalizers.skills import canonicalize_skill

_SOURCE = "github"
_WEIGHT = SOURCE_WEIGHTS[_SOURCE]

# Matches a GitHub user profile URL; captures the login name.
GITHUB_URL_RE = re.compile(r"https?://github\.com/([A-Za-z0-9_-]+)/?", re.I)

# Well-known GitHub language names -> canonical skill names.
# Languages not in this map are still included after canonicalization.
LANGUAGE_SKILL_MAP: dict[str, str] = {
    "Python": "Python",
    "Go": "Go",
    "Java": "Java",
    "JavaScript": "JavaScript",
    "TypeScript": "TypeScript",
    "Rust": "Rust",
    "C++": "C++",
    "Jupyter Notebook": "Jupyter",
}


def _parse_github_payload(data: dict, candidate_id: str | None) -> PartialRecord:
    """
    Build a PartialRecord from a normalised GitHub payload dict.

    This is the shared core used by both the mock reader and the live fetcher.
    """
    partial = PartialRecord(
        candidate_id=candidate_id or data.get("candidate_id"),
        full_name=data.get("name"),
        headline=data.get("bio") or None,
        links={
            "github": data.get("html_url"),
            "linkedin": None,
            "portfolio": None,
            "other": [],
        },
        source_name=_SOURCE,
        source_weight=_WEIGHT,
    )

    # Collect unique languages from public repos and convert to skills.
    skill_names: set[str] = set()
    for repo in data.get("repos") or []:
        lang = repo.get("language")
        if lang:
            mapped = LANGUAGE_SKILL_MAP.get(lang) or canonicalize_skill(lang)
            if mapped:
                skill_names.add(mapped)

    for name in sorted(skill_names):
        partial.skills.append(
            SkillEntry(name=name, confidence=_WEIGHT * 0.75, sources=[_SOURCE])
        )

    # Provenance for each populated field.
    for field_name, value in [
        ("full_name", partial.full_name),
        ("headline", partial.headline),
        ("links.github", partial.links.get("github")),
        ("skills", partial.skills),
    ]:
        if value:
            partial.provenance.append(
                ProvenanceEntry(
                    field=field_name,
                    source=_SOURCE,
                    method="github_api",
                    confidence=_WEIGHT,
                )
            )

    return partial


def parse_github_mock(path: Path) -> PartialRecord | None:
    """
    Load a GitHub profile from a local mock JSON file.

    Used for deterministic offline runs and tests.
    Returns None if the file is missing, unreadable, or malformed.
    """
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return _parse_github_payload(data, data.get("candidate_id"))


def fetch_github_profile(login: str, candidate_id: str | None = None) -> PartialRecord | None:
    """
    Fetch a GitHub user profile and their recent repos via the public API.

    Rate limit: 60 unauthenticated requests per hour.
    Returns None on any network error or non-200 status — never raises.
    """
    url = f"https://api.github.com/users/{login}"
    try:
        resp = requests.get(
            url,
            timeout=10,
            headers={"Accept": "application/vnd.github+json"},
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
    except requests.RequestException:
        return None

    # Fetch the user's most recently updated public repos for language signals.
    repos: list[dict] = []
    repos_url = data.get("repos_url")
    if repos_url:
        try:
            repos_resp = requests.get(
                repos_url,
                params={"per_page": 30, "sort": "updated"},
                timeout=10,
                headers={"Accept": "application/vnd.github+json"},
            )
            if repos_resp.status_code == 200:
                repos = [
                    {"name": r.get("name"), "language": r.get("language")}
                    for r in repos_resp.json()
                    if isinstance(r, dict)
                ]
        except requests.RequestException:
            pass  # Degrade gracefully — profile without repos is still useful.

    payload = {
        "candidate_id": candidate_id,
        "login": data.get("login"),
        "name": data.get("name"),
        "bio": data.get("bio"),
        "html_url": data.get("html_url"),
        "repos": repos,
    }
    return _parse_github_payload(payload, candidate_id)


def parse_github_from_notes_url(
    notes_text: str,
    candidate_id: str | None,
    mock_dir: Path | None = None,
) -> PartialRecord | None:
    """
    Extract a GitHub login from free-text notes and return a PartialRecord.

    If *mock_dir* is provided and a matching mock file exists, it is used
    instead of hitting the live API (keeps the pipeline deterministic).
    Returns None if no GitHub URL is found in the text.
    """
    match = GITHUB_URL_RE.search(notes_text)
    if not match:
        return None

    login = match.group(1)

    # Prefer mock over live API for reproducibility.
    if mock_dir and candidate_id:
        mock_path = mock_dir / f"github_mock_{candidate_id}.json"
        if mock_path.exists():
            return parse_github_mock(mock_path)

    return fetch_github_profile(login, candidate_id)
