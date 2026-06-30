"""
Test suite for the candidate data transformer.

Coverage:
  - Normalizers: phone, date, skill canonicalization, name, location
  - Merger: scalar conflict resolution, skill union, experience dedup
  - Projector: field remapping, array projection, on_missing policies
  - Validator: schema enforcement, date format checking
  - Pipeline: end-to-end default schema, custom config, graceful degradation
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from candidate_transformer.merger import (
    _merge_skills,
    _normalize_company,
    group_partials_by_candidate,
    merge_partials,
)
from candidate_transformer.models import PartialRecord, SkillEntry
from candidate_transformer.normalizers.phone import normalize_phone_e164
from candidate_transformer.normalizers.skills import canonicalize_skill, canonicalize_skills
from candidate_transformer.normalizers.text import (
    normalize_date,
    normalize_email,
    normalize_name,
    parse_location_string,
    years_between,
)
from candidate_transformer.pipeline import run_pipeline
from candidate_transformer.projector import ProjectionError, project_record
from candidate_transformer.validator import ValidationError, validate_canonical


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample_inputs"
CONFIG = ROOT / "config" / "custom_output.json"


# ---------------------------------------------------------------------------
# Phone normalizer
# ---------------------------------------------------------------------------

class TestNormalizePhone:
    def test_us_formatted(self):
        assert normalize_phone_e164("(415) 555-0198") == "+14155550198"

    def test_us_dashes(self):
        assert normalize_phone_e164("415-555-0198") == "+14155550198"

    def test_indian_10digit(self):
        assert normalize_phone_e164("9876543210", default_region="IN") == "+919876543210"

    def test_indian_with_spaces(self):
        assert normalize_phone_e164("+91 98765 43210", default_region="IN") == "+919876543210"

    def test_garbage_returns_none(self):
        assert normalize_phone_e164("not-a-phone") is None

    def test_empty_returns_none(self):
        assert normalize_phone_e164("") is None

    def test_none_input(self):
        assert normalize_phone_e164(None) is None

    def test_digits_only_us(self):
        # 10-digit US number without formatting
        assert normalize_phone_e164("4155550198") == "+14155550198"


# ---------------------------------------------------------------------------
# Date normalizer
# ---------------------------------------------------------------------------

class TestNormalizeDate:
    def test_already_yyyy_mm(self):
        assert normalize_date("2022-03") == "2022-03"

    def test_full_iso_date(self):
        assert normalize_date("2022-03-15") == "2022-03"

    def test_year_only(self):
        assert normalize_date("2020") == "2020-01"

    def test_month_abbreviation(self):
        assert normalize_date("Jan 2022") == "2022-01"
        assert normalize_date("September 2019") == "2019-09"

    def test_mm_slash_yyyy(self):
        assert normalize_date("3/2022") == "2022-03"
        assert normalize_date("12/2021") == "2021-12"

    def test_garbage_returns_none(self):
        assert normalize_date("garbage") is None

    def test_none_input(self):
        assert normalize_date(None) is None

    def test_blank_string(self):
        assert normalize_date("   ") is None


# ---------------------------------------------------------------------------
# Email normalizer
# ---------------------------------------------------------------------------

class TestNormalizeEmail:
    def test_lowercases(self):
        assert normalize_email("User@Example.COM") == "user@example.com"

    def test_valid(self):
        assert normalize_email("a@b.co") == "a@b.co"

    def test_no_at_sign(self):
        assert normalize_email("nodomain") is None

    def test_none(self):
        assert normalize_email(None) is None


# ---------------------------------------------------------------------------
# Name normalizer
# ---------------------------------------------------------------------------

class TestNormalizeName:
    def test_strips_whitespace(self):
        assert normalize_name("  priya sharma  ") == "Priya Sharma"

    def test_collapses_internal_spaces(self):
        # Multiple internal spaces are collapsed to one.
        assert normalize_name("John   O'Brien") == "John O'Brien"

    def test_all_caps_titlecased(self):
        assert normalize_name("AYUSH KUMAR") == "Ayush Kumar"

    def test_mixed_case_preserved(self):
        assert normalize_name("Maria Garcia") == "Maria Garcia"

    def test_none(self):
        assert normalize_name(None) is None


# ---------------------------------------------------------------------------
# Location parser
# ---------------------------------------------------------------------------

class TestParseLocationString:
    def test_city_state_country(self):
        result = parse_location_string("Bangalore, Karnataka, India")
        assert result["city"] == "Bangalore"
        assert result["region"] == "Karnataka"
        assert result["country"] == "IN"

    def test_city_us_state(self):
        result = parse_location_string("Austin, TX")
        assert result["city"] == "Austin"
        assert result["country"] == "US"

    def test_blank_returns_none(self):
        assert parse_location_string("") is None
        assert parse_location_string(None) is None

    def test_single_part(self):
        result = parse_location_string("India")
        assert result["country"] == "IN"


# ---------------------------------------------------------------------------
# Skill canonicalization
# ---------------------------------------------------------------------------

class TestCanonicalizeSkill:
    def test_lowercase_python(self):
        assert canonicalize_skill("python") == "Python"

    def test_alias_ml(self):
        assert canonicalize_skill("machine learning") == "Machine Learning"

    def test_unknown_titlecased(self):
        assert canonicalize_skill("Rust") == "Rust"

    def test_empty_returns_none(self):
        assert canonicalize_skill("") is None
        assert canonicalize_skill(None) is None

    def test_dedup_list(self):
        result = canonicalize_skills(["python", "Python", "py"])
        assert result == ["Python"]

    def test_preserves_order(self):
        result = canonicalize_skills(["Go", "python", "AWS"])
        assert result == ["Go", "Python", "AWS"]


# ---------------------------------------------------------------------------
# Merger internals
# ---------------------------------------------------------------------------

class TestMerger:
    def test_normalize_company_strips_suffix(self):
        assert _normalize_company("Infosys Ltd") == _normalize_company("Infosys")
        assert _normalize_company("Stripe Inc.") == _normalize_company("Stripe")

    def test_merge_skills_dedup(self):
        p1 = PartialRecord(
            source_name="ats_json", source_weight=0.9,
            skills=[SkillEntry("Python", 0.81, ["ats_json"])],
        )
        p2 = PartialRecord(
            source_name="github", source_weight=0.7,
            skills=[SkillEntry("Python", 0.525, ["github"]), SkillEntry("Go", 0.525, ["github"])],
        )
        merged = _merge_skills([p1, p2])
        names = [s.name for s in merged]
        assert names.count("Python") == 1
        python_skill = next(s for s in merged if s.name == "Python")
        assert python_skill.confidence == pytest.approx(0.81)
        assert set(python_skill.sources) == {"ats_json", "github"}
        assert "Go" in names

    def test_merge_partials_picks_highest_weight_name(self):
        low = PartialRecord(candidate_id="X", full_name="Low Weight Name",
                            source_name="recruiter_notes", source_weight=0.55)
        high = PartialRecord(candidate_id="X", full_name="High Weight Name",
                             source_name="ats_json", source_weight=0.9)
        result = merge_partials([low, high])
        assert result["full_name"] == "High Weight Name"

    def test_merge_partials_unions_emails(self):
        p1 = PartialRecord(candidate_id="X", emails=["a@x.com"],
                           source_name="ats_json", source_weight=0.9)
        p2 = PartialRecord(candidate_id="X", emails=["b@x.com"],
                           source_name="recruiter_csv", source_weight=0.85)
        result = merge_partials([p1, p2])
        assert "a@x.com" in result["emails"]
        assert "b@x.com" in result["emails"]

    def test_group_by_candidate_id(self):
        p1 = PartialRecord(candidate_id="CAND-001", source_name="csv", source_weight=0.85)
        p2 = PartialRecord(candidate_id="CAND-001", source_name="ats", source_weight=0.90)
        p3 = PartialRecord(candidate_id="CAND-002", source_name="csv", source_weight=0.85)
        groups = group_partials_by_candidate([p1, p2, p3])
        assert len(groups["CAND-001"]) == 2
        assert len(groups["CAND-002"]) == 1

    def test_group_fallback_to_email(self):
        p = PartialRecord(candidate_id=None, emails=["no-id@example.com"],
                          source_name="csv", source_weight=0.85)
        groups = group_partials_by_candidate([p])
        assert "no-id@example.com" in groups


# ---------------------------------------------------------------------------
# Projector
# ---------------------------------------------------------------------------

class TestProjector:
    def _canonical(self) -> dict:
        return {
            "candidate_id": "CAND-001",
            "full_name": "Priya Sharma",
            "emails": ["priya@example.com", "priya2@example.com"],
            "phones": ["+919876543210"],
            "location": {"city": "Bangalore", "region": None, "country": "IN"},
            "links": {"linkedin": None, "github": "https://github.com/p", "portfolio": None, "other": []},
            "headline": "Engineer at Infosys",
            "years_experience": 4.0,
            "skills": [{"name": "Python", "confidence": 0.81, "sources": ["ats_json"]}],
            "experience": [],
            "education": [],
            "provenance": [],
            "overall_confidence": 0.87,
        }

    def test_simple_field_selection(self):
        config = {"fields": [{"path": "full_name", "type": "string"}], "on_missing": "null"}
        result = project_record(self._canonical(), config)
        assert result == {"full_name": "Priya Sharma"}

    def test_email_remap(self):
        config = {
            "fields": [{"path": "primary_email", "from": "emails[0]", "type": "string"}],
            "on_missing": "null",
        }
        result = project_record(self._canonical(), config)
        assert result["primary_email"] == "priya@example.com"

    def test_array_projection(self):
        config = {
            "fields": [{"path": "skill_names", "from": "skills[].name", "type": "string[]"}],
            "on_missing": "null",
        }
        result = project_record(self._canonical(), config)
        assert result["skill_names"] == ["Python"]

    def test_on_missing_null(self):
        config = {
            "fields": [{"path": "missing_field", "from": "nonexistent", "type": "string"}],
            "on_missing": "null",
        }
        result = project_record(self._canonical(), config)
        assert result["missing_field"] is None

    def test_on_missing_omit(self):
        config = {
            "fields": [{"path": "missing_field", "from": "nonexistent", "type": "string"}],
            "on_missing": "omit",
        }
        result = project_record(self._canonical(), config)
        assert "missing_field" not in result

    def test_on_missing_error_required(self):
        config = {
            "fields": [{"path": "missing_field", "from": "nonexistent[99]",
                        "type": "string", "required": True}],
            "on_missing": "error",
        }
        with pytest.raises(ProjectionError):
            project_record(self._canonical(), config)

    def test_include_confidence(self):
        config = {"fields": [], "include_confidence": True, "on_missing": "null"}
        result = project_record(self._canonical(), config)
        assert result["overall_confidence"] == pytest.approx(0.87)

    def test_include_provenance_false(self):
        config = {"fields": [], "include_provenance": False, "on_missing": "null"}
        result = project_record(self._canonical(), config)
        assert "provenance" not in result

    def test_normalize_e164(self):
        config = {
            "fields": [{"path": "phone", "from": "phones[0]", "type": "string",
                        "normalize": "E164"}],
            "on_missing": "null",
        }
        result = project_record(self._canonical(), config)
        assert result["phone"] == "+919876543210"

    def test_nested_path(self):
        config = {
            "fields": [{"path": "github_url", "from": "links.github", "type": "string"}],
            "on_missing": "null",
        }
        result = project_record(self._canonical(), config)
        assert result["github_url"] == "https://github.com/p"


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class TestValidator:
    def _valid(self) -> dict:
        return {
            "candidate_id": "CAND-001",
            "full_name": "Test User",
            "emails": [],
            "phones": [],
            "location": None,
            "links": {"linkedin": None, "github": None, "portfolio": None, "other": []},
            "headline": None,
            "years_experience": None,
            "skills": [],
            "experience": [],
            "education": [],
            "provenance": [],
            "overall_confidence": 0.5,
        }

    def test_valid_record_passes(self):
        validate_canonical(self._valid())  # Should not raise.

    def test_missing_field_raises(self):
        record = self._valid()
        del record["emails"]
        with pytest.raises(ValidationError, match="emails"):
            validate_canonical(record)

    def test_bad_date_format_raises(self):
        record = self._valid()
        record["experience"] = [{"company": "A", "title": "B", "start": "bad-date",
                                  "end": None, "summary": None}]
        with pytest.raises(ValidationError):
            validate_canonical(record)

    def test_phones_not_list_raises(self):
        record = self._valid()
        record["phones"] = "not-a-list"
        with pytest.raises(ValidationError, match="phones"):
            validate_canonical(record)

    def test_years_experience_wrong_type(self):
        record = self._valid()
        record["years_experience"] = "four"
        with pytest.raises(ValidationError, match="years_experience"):
            validate_canonical(record)

    def test_provenance_missing_key_raises(self):
        record = self._valid()
        record["provenance"] = [{"field": "name", "source": "csv"}]  # missing "method"
        with pytest.raises(ValidationError, match="method"):
            validate_canonical(record)


# ---------------------------------------------------------------------------
# Pipeline — end to end
# ---------------------------------------------------------------------------

class TestPipeline:
    def test_default_schema_produces_valid_records(self):
        records = run_pipeline(
            csv_path=SAMPLE / "recruiter_export.csv",
            ats_path=SAMPLE / "ats_candidates.json",
            notes_dir=SAMPLE,
            mock_dir=SAMPLE,
        )
        assert len(records) >= 3
        for record in records:
            validate_canonical(record)

    def test_priya_merged_correctly(self):
        records = run_pipeline(
            csv_path=SAMPLE / "recruiter_export.csv",
            ats_path=SAMPLE / "ats_candidates.json",
            notes_dir=SAMPLE,
            mock_dir=SAMPLE,
        )
        priya = next(r for r in records if r["candidate_id"] == "CAND-001")
        assert priya["full_name"]
        assert "priya.sharma@email.com" in priya["emails"]
        assert any(p.startswith("+") for p in priya["phones"])
        assert priya["overall_confidence"] > 0

        # Skills should be merged from ATS + GitHub mock
        skill_names = {s["name"] for s in priya["skills"]}
        assert "Python" in skill_names
        python = next(s for s in priya["skills"] if s["name"] == "Python")
        assert set(python["sources"]) >= {"ats_json", "github"}

    def test_graceful_on_garbage_row(self):
        # CAND-004 has an invalid phone and no company — pipeline must not crash.
        records = run_pipeline(
            csv_path=SAMPLE / "recruiter_export.csv",
            ats_path=None,
            notes_dir=None,
        )
        bad = next((r for r in records if r["candidate_id"] == "CAND-004"), None)
        if bad:
            assert bad["phones"] == []

    def test_custom_config_renames_fields(self):
        with CONFIG.open() as f:
            config = json.load(f)

        records = run_pipeline(
            csv_path=SAMPLE / "recruiter_export.csv",
            ats_path=SAMPLE / "ats_candidates.json",
            notes_dir=SAMPLE,
            mock_dir=SAMPLE,
            output_config=config,
        )
        assert len(records) >= 1
        first = records[0]
        assert "primary_email" in first
        assert "skill_names" in first
        assert "provenance" not in first        # include_provenance is False in config
        assert "overall_confidence" in first    # include_confidence is True

    def test_csv_only_produces_records(self):
        records = run_pipeline(
            csv_path=SAMPLE / "recruiter_export.csv",
            ats_path=None,
            notes_dir=None,
        )
        assert len(records) >= 3

    def test_missing_source_does_not_crash(self):
        records = run_pipeline(
            csv_path=Path("/nonexistent/file.csv"),
            ats_path=None,
            notes_dir=None,
        )
        assert records == []

    def test_provenance_present_in_output(self):
        records = run_pipeline(
            csv_path=SAMPLE / "recruiter_export.csv",
            ats_path=SAMPLE / "ats_candidates.json",
            notes_dir=None,
        )
        priya = next(r for r in records if r["candidate_id"] == "CAND-001")
        assert len(priya["provenance"]) > 0
        sources_used = {p["source"] for p in priya["provenance"]}
        assert "ats_json" in sources_used
