# Candidate Transformer

Multi-source candidate data transformer that ingests structured and unstructured sources, merges them into canonical profiles with provenance and confidence, and supports runtime output projection.

## Demo Video

[Watch the demo (~2 min)](https://drive.google.com/file/d/14yBO8KSpWd2jk8Gy2nLZxrDjVJXdAHIL/view?usp=sharing)

## Sources implemented

| Type | Source | Parser |
|------|--------|--------|
| Structured | Recruiter CSV export | `parsers/csv_parser.py` |
| Structured | ATS JSON blob | `parsers/ats_parser.py` |
| Unstructured | Recruiter notes (.txt) + GitHub | `parsers/notes_parser.py`, `parsers/github_parser.py` |

GitHub data is loaded from mock JSON files in `data/sample_inputs/` for deterministic offline runs. Live GitHub API fetch is supported when mocks are absent.

## Setup

```bash
cd eightfold
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run (default canonical schema)

```bash
python -m candidate_transformer.cli \
  --csv data/sample_inputs/recruiter_export.csv \
  --ats data/sample_inputs/ats_candidates.json \
  --notes-dir data/sample_inputs \
  --mock-dir data/sample_inputs \
  -o data/sample_outputs/default_profiles.json
```

## Run (custom projection config)

```bash
python -m candidate_transformer.cli \
  --csv data/sample_inputs/recruiter_export.csv \
  --ats data/sample_inputs/ats_candidates.json \
  --notes-dir data/sample_inputs \
  --mock-dir data/sample_inputs \
  --config config/custom_output.json \
  -o data/sample_outputs/custom_profiles.json
```

## Tests

```bash
pytest -v
```

## Pipeline

```
load sources → parse partial records → group by candidate_id
  → merge + conflict resolution → validate canonical
  → (optional) project to custom schema → write JSON
```

## Design decisions

- **Match key:** `candidate_id` primary; email fallback for unlabeled fragments
- **Conflict resolution:** Highest source weight wins (ATS > CSV > GitHub > notes)
- **Confidence:** Per-field source weights; overall = mean of populated field confidences
- **Philosophy:** Unparseable values become `null` — never invented

## Assumptions & descoped

- Sample inputs created locally (Box link hosts assignment PDF only)
- GitHub uses offline mocks for deterministic demo; live API optional
- LinkedIn scraping not implemented (ToS / auth complexity)
- Resume PDF/DOCX parsing descoped
- Location country inference is heuristic (not geocoding API)