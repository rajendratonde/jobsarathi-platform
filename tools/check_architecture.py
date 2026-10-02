"""Architecture guard-rails, run locally and (later) in CI.

Checks that the code still follows the approved design:
  1. every table a service defines exists in the v5 catalogue for that service's database
  2. no foreign key leaves the service's own database
  3. soft-delete columns only on tables v5 classifies YES/SPECIAL, always with the deleted_by check
  4. no service imports another service's package
  5. no obvious hard-coded secret and no committed .env
  6. no product or vendor that belongs to an undecided T2-T6 decision appears in code or config
  7. local ports are bound to 127.0.0.1 only
  8. an implemented table has exactly the catalogue's columns (none missing, none extra)
  9. authorization is data-driven: no role names in code, no role compared with a literal

Exit code 1 on any failure.  Usage:  python tools/check_architecture.py
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = json.loads((ROOT / "docs" / "erd" / "v5-table-catalogue.json").read_text(encoding="utf-8"))
SERVICES = {
    "identity": "identity_service", "candidate": "candidate_service", "employer": "employer_service",
    "job": "job_service", "application": "application_service", "learning": "learning_service",
    "engagement": "engagement_service", "reference": "reference_service",
}
# Words that would mean a T2-T6 decision slipped into code/config (docs may discuss them).
UNDECIDED = re.compile(
    r"\b(kong|traefik|krakend|tyk|apigee|keycloak|auth0|cognito|okta|sendgrid|mailgun|amazon ses|aws ses|postmark|"
    r"twilio|msg91|gupshup|kafka|rabbitmq|redis|terraform|cloudformation|pulumi|github actions|gitlab|jenkins|"
    r"mulesoft|wso2|boomi|aws_access_key_id)\b", re.I)
SECRET_LITERAL = re.compile(
    r"""(password|secret|api_key|token)\s*[:=]\s*["']"""
    r"""(?!change-me|local-dev-only|\*\*\*|env:|file:)[^"'\s]{6,}["']""", re.I)

failures: list[str] = []


def fail(message: str) -> None:
    failures.append(message)


def check_models() -> None:
    sys.path[:0] = [str(ROOT / "services" / key) for key in SERVICES]
    for key, package in SERVICES.items():
        db = f"{key}_db"
        allowed = CATALOGUE["databases"][db]["tables"]
        models = importlib.import_module(f"{package}.models")
        metadata = models.Base.metadata
        for name, table in metadata.tables.items():
            if name not in allowed:
                fail(f"{db}: table '{name}' is not in the v5 catalogue for {db}")
                continue
            v5_cols = {c["name"] for c in allowed[name]["columns"]}
            extra = {c.name for c in table.columns} - v5_cols
            if extra:
                fail(f"{db}.{name}: columns not in v5: {sorted(extra)}")
            missing = v5_cols - {c.name for c in table.columns}
            if missing:
                fail(f"{db}.{name}: v5 columns missing from the model: {sorted(missing)}")
            for fk in table.foreign_keys:
                if fk.column.table.name not in metadata.tables or fk.column.table.metadata is not metadata:
                    fail(f"{db}.{name}: foreign key to '{fk.target_fullname}' leaves {db}")
            has_soft = "deleted_at" in table.columns
            if has_soft and allowed[name]["soft_delete"] == "NO":
                fail(f"{db}.{name}: soft-delete columns on a table v5 classifies NO")
            if has_soft and not any("deleted_at IS NULL OR deleted_by IS NOT NULL" in str(getattr(c, "sqltext", ""))
                                    for c in table.constraints):
                fail(f"{db}.{name}: soft-delete table missing the deleted_by check")
        print(f"  {db:<16} tables: {', '.join(sorted(metadata.tables))}")


def check_imports() -> None:
    for key, package in SERVICES.items():
        others = [p for p in SERVICES.values() if p != package]
        pattern = re.compile(r"^\s*(from|import)\s+(" + "|".join(others) + r")\b", re.M)
        for path in (ROOT / "services" / key).rglob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8")):
                fail(f"{path.relative_to(ROOT)} imports another service's package")


# Role names that must never drive authorization in code (roles are rows in identity_db).
ROLE_WORDS = re.compile(r"^(super[ _-]?admin|platform[ _-]?admin(istrator)?|admin(istrator)?|recruiter|hr[ _-]?manager|"
                        r"employer[ _-]?admin|candidate[ _-]?role|college[ _-]?admin)$", re.I)
SEEDED_ROLE_CODES = {"PLATFORM_ADMIN", "CANDIDATE"}


def _docstrings(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def check_rbac_data_driven() -> None:
    """Python: no role-name string literals and no role compared with a literal.
    Frontend: no role names in source (it renders from /me/permissions)."""
    for key in SERVICES:
        for path in (ROOT / "services" / key).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if "/migrations/" in rel or "/tests/" in rel:
                continue  # seeds are data; tests may name the roles they create
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docs = _docstrings(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                    if ROLE_WORDS.match(node.value.strip()) or node.value in SEEDED_ROLE_CODES:
                        fail(f"{rel}:{node.lineno}: role name '{node.value}' in code; use permission codes")
                if isinstance(node, ast.Compare):
                    sides = [node.left, *node.comparators]
                    names = {getattr(side, "attr", getattr(side, "id", "")) for side in sides}
                    if names & {"role_code", "roles", "role_name"} and any(
                            isinstance(side, ast.Constant) and isinstance(side.value, str) for side in sides):
                        fail(f"{rel}:{node.lineno}: role compared with a literal; authorize by permission code")
    words = re.compile(r"""["'`](super ?admin|platform ?admin(istrator)?|PLATFORM_ADMIN|recruiter|hr ?manager)["'`]""",
                       re.I)
    frontend = ROOT / "frontend" / "src"
    for path in [*frontend.rglob("*.ts"), *frontend.rglob("*.tsx")]:
        if ".test." in path.name:
            continue
        match = words.search(path.read_text(encoding="utf-8"))
        if match:
            fail(f"{path.relative_to(ROOT).as_posix()}: role name {match.group(0)} in UI code; use permissions")


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout
        return [ROOT / line for line in out.splitlines() if line]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*") if p.is_file() and ".venv" not in p.parts and "node_modules" not in p.parts]


def check_files() -> None:
    files = tracked_files()
    if any(p.name == ".env" for p in files):
        fail(".env is tracked by git; it must stay local")
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix not in {".py", ".yml", ".yaml", ".toml", ".ini", ".sh", ".ts", ".tsx", ".json", ".example",
                               ".mako"} and path.name not in {"Dockerfile", ".env.example"}:
            continue
        if rel.startswith(("docs/", "tools/check_architecture.py")) or "package-lock" in rel:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        is_test = "/tests/" in f"/{rel}" or ".test." in path.name or path.name == "test-utils.ts"
        if not is_test and SECRET_LITERAL.search(text):
            fail(f"{rel}: looks like a hard-coded secret")
        match = UNDECIDED.search(text)
        if match:
            fail(f"{rel}: mentions '{match.group(0)}', which belongs to an undecided T2-T6 decision")
    compose = (ROOT / "infrastructure" / "local" / "docker-compose.yml").read_text(encoding="utf-8")
    for port in re.findall(r'-?\s*"([^"]*:\d+:\d+)"|\["([^"]+)"\]', compose):
        value = port[0] or port[1]
        if value and not value.startswith("127.0.0.1:") and re.match(r"^[\d.:]+$", value):
            fail(f"docker-compose port '{value}' is not bound to 127.0.0.1")


def main() -> int:
    print("Architecture check")
    check_models()
    check_imports()
    check_rbac_data_driven()
    check_files()
    if failures:
        print("\nFAILED:")
        for message in failures:
            print(f"  - {message}")
        return 1
    print("\nOK: v5 tables only, no cross-database FK, no cross-service imports, data-driven RBAC, no secrets, no T2-T6 products")
    return 0


if __name__ == "__main__":
    sys.exit(main())
