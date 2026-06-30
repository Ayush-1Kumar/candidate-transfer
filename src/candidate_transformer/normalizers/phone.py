"""
Phone number normalizer using the libphonenumber library.

Converts any phone string to E.164 format (e.g. +14155550198).
Returns None for invalid or unrecognisable input — never invented.
"""
from __future__ import annotations

import phonenumbers
from phonenumbers import NumberParseException


def normalize_phone_e164(value: str | None, default_region: str = "US") -> str | None:
    """
    Parse and format a phone number string to E.164.

    Args:
        value: Raw phone string from any source.
        default_region: ISO alpha-2 country code used when the number has no
            country code prefix (e.g. "US" or "IN").

    Returns:
        E.164 string (e.g. "+14155550198") or None if unparseable / invalid.
    """
    if not value or not str(value).strip():
        return None

    text = str(value).strip()
    digits_only = "".join(c for c in text if c.isdigit())

    # Heuristic: 10-digit Indian mobile numbers (start with 6–9) lack the +91
    # country code when exported from Indian ATS systems.
    if (
        len(digits_only) == 10
        and not text.startswith("+")
        and digits_only[0] in "6789"
        and default_region == "IN"
    ):
        text = f"+91{digits_only}"

    try:
        parsed = phonenumbers.parse(text, default_region)
        if not phonenumbers.is_valid_number(parsed):
            return None
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except NumberParseException:
        return None
