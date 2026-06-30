"""
Skill name canonicalization.

Maps common aliases and casing variants to a single canonical name so that
"python", "Python", and "py" all merge into one "Python" skill entry.
Extend SKILL_ALIASES to add new mappings without changing any pipeline code.
"""
from __future__ import annotations

# Maps lowercase alias -> canonical display name.
SKILL_ALIASES: dict[str, str] = {
    # Python
    "python": "Python",
    "py": "Python",
    # Java / JVM
    "java": "Java",
    # JavaScript / TypeScript
    "javascript": "JavaScript",
    "js": "JavaScript",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    # Go
    "go": "Go",
    "golang": "Go",
    # Cloud
    "aws": "AWS",
    "amazon web services": "AWS",
    # Machine Learning
    "machine learning": "Machine Learning",
    "ml": "Machine Learning",
    # Systems / Infra
    "distributed systems": "Distributed Systems",
    # Databases
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "sql": "SQL",
    "mysql": "MySQL",
    "mongodb": "MongoDB",
    # Data / BI
    "excel": "Excel",
    "tableau": "Tableau",
    "jupyter notebook": "Jupyter",
    "jupyter": "Jupyter",
    # DevOps / Cloud (common additions)
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "gcp": "GCP",
    "google cloud": "GCP",
    "azure": "Azure",
    # Misc
    "react": "React",
    "node": "Node.js",
    "node.js": "Node.js",
    "nodejs": "Node.js",
    "rust": "Rust",
    "c++": "C++",
    "cpp": "C++",
}


def canonicalize_skill(name: str | None) -> str | None:
    """
    Return the canonical display name for a skill.

    Looks up the lowercase-trimmed input in SKILL_ALIASES; falls back to
    title-casing the input when no alias matches.
    Returns None for blank/None input.
    """
    if not name or not name.strip():
        return None
    key = name.strip().lower()
    return SKILL_ALIASES.get(key, name.strip().title())


def canonicalize_skills(names: list[str]) -> list[str]:
    """
    Canonicalize a list of skill names, preserving insertion order and
    removing duplicates (case-insensitively after canonicalization).
    """
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        canonical = canonicalize_skill(name)
        if canonical and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result
