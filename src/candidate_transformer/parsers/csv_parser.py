"""
Recruiter CSV parser.

Expects a CSV with columns: candidate_id, name, email, phone,
current_company, title, location.
Any column may be missing or blank — the parser degrades gracefully.
"""
from __future__ import annotations

import csv
from pathlib import Path

from candidate_transformer.models import (
    ExperienceEntry,
    PartialRecord,
    ProvenanceEntry,
    SOURCE_WEIGHTS,
)
from candidate_transformer.normalizers.phone import normalize_phone_e164
from candidate_transformer.normalizers.text import (
    normalize_email,
    normalize_name,
    parse_location_string,
)

_SOURCE = "recruiter_csv"
_WEIGHT = SOURCE_WEIGHTS[_SOURCE]


def parse_recruiter_csv(path: Path) -> list[PartialRecord]:
    """
    Parse a recruiter CSV export into a list of PartialRecords.

    One PartialRecord is produced per data row.  Rows with all-blank identity
    fields are still returned (with empty lists) so the pipeline can decide
    whether to discard them.

    Args:
        path: Absolute path to the CSV file.

    Returns:
        List of PartialRecord instances, one per CSV row.

    Raises:
        OSError: If the file cannot be opened.
        csv.Error: If the file is not valid CSV.
    """
    records: list[PartialRecord] = []

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            candidate_id = (row.get("candidate_id") or "").strip() or None
            name = normalize_name(row.get("name"))
            email = normalize_email(row.get("email"))
            # CSV data may originate from multiple countries; default to US but
            # a real integration would carry a per-file region hint.
            phone = normalize_phone_e164(row.get("phone"), default_region="US")
            location = parse_location_string(row.get("location"))
            company = (row.get("current_company") or "").strip() or None
            title = (row.get("title") or "").strip() or None

            headline = f"{title} at {company}" if title and company else title

            partial = PartialRecord(
                candidate_id=candidate_id,
                full_name=name,
                emails=[email] if email else [],
                phones=[phone] if phone else [],
                location=location,
                headline=headline,
                source_name=_SOURCE,
                source_weight=_WEIGHT,
            )

            # Treat the current company + title column as the most recent role.
            if company and title:
                partial.experience.append(
                    ExperienceEntry(
                        company=company,
                        title=title,
                        start=None,   # CSV has no start date for current role
                        end=None,     # None signals "current"
                        summary=None,
                    )
                )
                partial.provenance.append(
                    ProvenanceEntry(
                        field="experience",
                        source=_SOURCE,
                        method="csv_current_role",
                        confidence=_WEIGHT * 0.8,
                    )
                )

            # Record provenance for every non-null field.
            for field_name, value in [
                ("candidate_id", candidate_id),
                ("full_name", name),
                ("emails", email),
                ("phones", phone),
                ("location", location),
                ("headline", headline),
            ]:
                if value:
                    partial.provenance.append(
                        ProvenanceEntry(
                            field=field_name,
                            source=_SOURCE,
                            method="csv_column",
                            confidence=_WEIGHT,
                        )
                    )

            records.append(partial)

    return records
