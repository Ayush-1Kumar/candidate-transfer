"""
Text normalizers for dates, emails, names, and location strings.

All functions are pure (no side effects) and return None instead of raising
when input is unparseable — "honestly empty beats wrong-but-confident."
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

# Maps 3-letter month abbreviation to zero-padded month number.
_MONTH_MAP: dict[str, str] = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

# ISO-3166 alpha-2 lookup for common location strings found in recruiter data.
_COUNTRY_MAP: dict[str, str] = {
    "india": "IN",
    "usa": "US",
    "united states": "US",
    "ca": "US",        # state abbreviation often mistaken for country
    "california": "US",
    "tx": "US",
    "texas": "US",
    "uk": "GB",
    "united kingdom": "GB",
    "canada": "CA",
    "germany": "DE",
    "australia": "AU",
    "singapore": "SG",
}


def normalize_date(value: str | None) -> str | None:
    """
    Normalize a heterogeneous date string to YYYY-MM.

    Handles: YYYY-MM, YYYY-MM-DD, YYYY, "Jan 2022", "03/2022".
    Returns None for unparseable input — never guesses.
    """
    if not value or not str(value).strip():
        return None

    text = str(value).strip()

    if re.fullmatch(r"\d{4}-\d{2}", text):
        return text

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        # Truncate to year-month; day precision not needed.
        return text[:7]

    if re.fullmatch(r"\d{4}", text):
        # Year-only: default to January as a conservative fallback.
        return f"{text}-01"

    # "Jan 2022" or "January 2022"
    match = re.match(r"^([A-Za-z]{3,9})\s+(\d{4})$", text)
    if match:
        month = _MONTH_MAP.get(match.group(1).lower()[:3])
        if month:
            return f"{match.group(2)}-{month}"

    # "03/2022" or "3/2022"
    match = re.match(r"^(\d{1,2})/(\d{4})$", text)
    if match:
        return f"{match.group(2)}-{int(match.group(1)):02d}"

    return None


def normalize_email(value: str | None) -> str | None:
    """
    Lowercase and validate an email address.

    Returns None if the value is not a valid email — does not attempt repair.
    """
    if not value:
        return None
    email = value.strip().lower()
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return email
    return None


def normalize_name(value: str | None) -> str | None:
    """
    Clean and title-case a candidate name.

    Collapses internal whitespace and title-cases all-lower or all-upper input
    while preserving mixed-case names (e.g. "O'Brien") unchanged.
    """
    if not value:
        return None
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return None
    # Only force title-case when the name is entirely one case — preserves
    # intentional capitalisation like "O'Brien" or "de la Cruz".
    return cleaned.title() if cleaned.islower() or cleaned.isupper() else cleaned


def parse_location_string(value: str | None) -> dict[str, str | None] | None:
    """
    Parse a free-text location string into structured city / region / country.

    Supports "City, State" and "City, State, Country" patterns.
    Country is resolved to ISO-3166 alpha-2 when recognised; otherwise None.
    Returns None when the input is blank or has no parseable parts.
    """
    if not value or not value.strip():
        return None

    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        return None

    city = parts[0]

    if len(parts) == 1:
        # Only a city (or country) name — can't infer region.
        country = _COUNTRY_MAP.get(city.lower())
        return {"city": city if not country else None, "region": None, "country": country}

    if len(parts) == 2:
        # "City, Country" or "City, State"
        region_or_country = parts[1]
        country = _COUNTRY_MAP.get(region_or_country.lower())
        # If the second part resolves to a country, it is not a region.
        region = region_or_country if not country else None
        return {"city": city, "region": region, "country": country}

    # Three or more parts: "City, State, Country"
    region = parts[1]
    country_raw = parts[-1].lower()
    country = _COUNTRY_MAP.get(country_raw)
    return {"city": city, "region": region, "country": country}


def years_between(start: str | None, end: str | None = None) -> float | None:
    """
    Calculate the number of years between two YYYY-MM dates.

    If *end* is None or unparseable, the current month is used.
    Returns None when *start* cannot be parsed.
    """
    start_norm = normalize_date(start)
    if not start_norm:
        return None
    try:
        start_dt = datetime.strptime(start_norm, "%Y-%m")
    except ValueError:
        return None

    if end:
        end_norm = normalize_date(end)
        end_dt = (
            datetime.strptime(end_norm, "%Y-%m")
            if end_norm
            else datetime.now(UTC).replace(tzinfo=None)
        )
    else:
        end_dt = datetime.now(UTC).replace(tzinfo=None)

    months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
    return round(max(months, 0) / 12.0, 1)
