#!/usr/bin/env python3
"""Repository-wide structural validator for Doctore Agent Skills."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


def skill_dirs() -> list[Path]:
    return sorted(path.parent for path in (ROOT / "skills").rglob("SKILL.md"))


def parse_skill(path: Path) -> tuple[dict, str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) != 3:
        raise ValueError("unterminated YAML frontmatter")
    _, frontmatter, body = parts
    data = yaml.safe_load(frontmatter) or {}
    if not isinstance(data, dict):
        raise ValueError("frontmatter must be a mapping")
    return data, body.strip(), text


def main() -> int:
    errors: list[str] = []
    directories = skill_dirs()
    if not directories:
        errors.append("no skills found")

    names: set[str] = set()
    for directory in directories:
        skill_file = directory / "SKILL.md"
        try:
            frontmatter, body, text = parse_skill(skill_file)
        except Exception as exc:
            errors.append(f"{skill_file.relative_to(ROOT)}: {exc}")
            continue

        unknown = set(frontmatter) - ALLOWED
        if unknown:
            errors.append(f"{skill_file.relative_to(ROOT)}: unsupported fields {sorted(unknown)}")

        name = frontmatter.get("name")
        description = frontmatter.get("description")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name) or len(name) > 64:
            errors.append(f"{skill_file.relative_to(ROOT)}: invalid name")
        if name != directory.name:
            errors.append(
                f"{skill_file.relative_to(ROOT)}: name must match directory '{directory.name}'"
            )
        if isinstance(name, str):
            if name in names:
                errors.append(f"duplicate skill name: {name}")
            names.add(name)

        if not isinstance(description, str) or not description.strip() or len(description) > 1024:
            errors.append(f"{skill_file.relative_to(ROOT)}: invalid description")
        elif "Use when" not in description:
            errors.append(
                f"{skill_file.relative_to(ROOT)}: description must include explicit 'Use when' trigger"
            )

        tools = frontmatter.get("allowed-tools")
        if tools is not None and not isinstance(tools, str):
            errors.append(
                f"{skill_file.relative_to(ROOT)}: allowed-tools must be a space-separated string"
            )

        if not body:
            errors.append(f"{skill_file.relative_to(ROOT)}: empty body")
        if len(text.splitlines()) > 500:
            errors.append(f"{skill_file.relative_to(ROOT)}: SKILL.md exceeds 500 lines")

        for relative in re.findall(r"(?:references|scripts)/[A-Za-z0-9_.-]+", body):
            if not (directory / relative).exists():
                errors.append(
                    f"{skill_file.relative_to(ROOT)}: missing referenced file {relative}"
                )

        scripts_dir = directory / "scripts"
        if scripts_dir.exists():
            for script in scripts_dir.iterdir():
                if (
                    script.is_file()
                    and script.suffix == ".py"
                    and not script.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3")
                ):
                    errors.append(f"{script.relative_to(ROOT)}: missing Python shebang")

    if errors:
        print("INVALID")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"VALID: {len(directories)} skills")
    for directory in directories:
        print(f"- {directory.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
