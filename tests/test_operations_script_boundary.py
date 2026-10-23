"""Architecture ratchet for every Python operations script, including nested files."""
import ast
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_MODULES = {
    "modules.application.operations_facade": frozenset({"OperationsFacade"}),
    "modules.application.operations_dto": frozenset({
        "MigrationStep", "PrecisionPreflightRequest", "ScheduleOperationError",
    }),
}


def _import_violations(tree):
    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
            if node.module == "modules":
                names.extend(f"modules.{item.name}" for item in node.names)
            if node.module in ALLOWED_MODULES:
                result.extend(
                    f"{node.module}:{item.name}"
                    for item in node.names if item.name not in ALLOWED_MODULES[node.module]
                )
        else:
            continue
        result.extend(name for name in names if (
            name == "modules" or name.startswith("modules.")
            or name in {"server", "app", "flask"}
            or name.startswith("flask.")
        ) and name not in ALLOWED_MODULES)

    importlib_names = set()
    import_module_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            importlib_names.update(
                alias.asname or alias.name.split(".")[0]
                for alias in node.names
                if alias.name == "importlib" or alias.name.startswith("importlib.")
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            import_module_names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "import_module"
            )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = node.func
        is_dynamic_import = (
            isinstance(function, ast.Name)
            and (function.id == "__import__" or function.id in import_module_names)
        ) or (
            isinstance(function, ast.Attribute)
            and function.attr == "import_module"
            and isinstance(function.value, ast.Name)
            and function.value.id in importlib_names
        )
        module_name = node.args[0]
        if (
            is_dynamic_import
            and isinstance(module_name, ast.Constant)
            and isinstance(module_name.value, str)
        ):
            name = module_name.value
            if (
                name == "modules" or name.startswith("modules.")
                or name in {"server", "app", "flask"}
                or name.startswith("flask.")
            ) and name not in ALLOWED_MODULES:
                result.append(name)
    return result


def _violations(source):
    tree = ast.parse(source)
    result = _import_violations(tree)
    # Include Python executed with subprocess -c; an import inside a string is
    # still an operations dependency, not an escape hatch for the gate.
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                embedded = ast.parse(node.value)
            except (SyntaxError, ValueError):
                continue
            result.extend(_import_violations(embedded))
    return result


def _extract_python_fragments(source):
    """Extract literal bodies passed to ``python -c`` in shell entry points."""
    marker = re.compile(r"\bpython(?:3)?\s+-c\s+(?:\\\s*)?")
    fragments = []
    for match in marker.finditer(source):
        index = match.end()
        while index < len(source) and source[index].isspace():
            index += 1
        if index >= len(source) or source[index] not in {"'", '"'}:
            continue
        quote = source[index]
        index += 1
        body = []
        escaped = False
        while index < len(source):
            character = source[index]
            if quote == '"' and escaped:
                body.append(character)
                escaped = False
            elif quote == '"' and character == "\\":
                escaped = True
            elif character == quote:
                break
            else:
                body.append(character)
            index += 1
        if index < len(source) and source[index] == quote:
            fragments.append("".join(body))
    return fragments


def _operation_script_paths(root):
    yield from sorted(path for path in root.glob("*.sh") if not path.name.startswith(".tmp"))
    yield from sorted(
        path for path in (root / "scripts").rglob("*.sh")
        if not any(part == ".worktrees" or part.startswith(".tmp") for part in path.relative_to(root).parts)
    )


def assert_script_boundaries(root=ROOT):
    errors = []
    for path in sorted(
        path for path in (root / "scripts").rglob("*.py")
        if not any(part == ".worktrees" or part.startswith(".tmp") for part in path.relative_to(root).parts)
    ):
        source = path.read_text(encoding="utf-8-sig")
        violations = _violations(source)
        if violations:
            errors.append(f"{path.relative_to(root).as_posix()}: {violations}")
    for path in _operation_script_paths(root):
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        for fragment in _extract_python_fragments(source):
            violations = _violations(fragment)
            if violations:
                errors.append(f"{path.relative_to(root).as_posix()}: {violations}")
    assert errors == [], "\n".join(errors)


def test_all_operational_scripts_use_stable_boundary():
    assert_script_boundaries()


@pytest.mark.parametrize("source", [
    "from modules.services.schedule_capacity_service import ScheduleCapacityService",
    "from modules.repositories.schedule_planning_repository import SchedulePlanningRepository",
    "from modules import migrations",
    "from modules.migration_production_nodes import m093_schedule_conflict_risk_evidence",
    "from modules.bootstrap import load_environment",
    "from server import app",
    "from flask import Flask",
    'command = "from modules.services.schedule_capacity_service import ScheduleCapacityService"',
    "from modules.application.operations_facade import ScheduleCapacityService",
    "import importlib; importlib.import_module('modules.services.schedule_capacity_service')",
    "import importlib as loader; loader.import_module('modules.repositories.schedule_planning_repository')",
    "import importlib.util; importlib.import_module('modules.repositories.schedule_planning_repository')",
    "from importlib import import_module as load; load('modules.migrations')",
    "__import__('modules.bootstrap')",
    'command = "__import__(\'modules.repositories.schedule_planning_repository\')"',
])
def test_nested_or_embedded_dependency_fixture_is_blocked(source, tmp_path):
    nested = tmp_path / "scripts/nested"
    nested.mkdir(parents=True)
    (nested / "invalid.py").write_text(source, encoding="utf-8")
    # The Python scan fails before it needs shell entry points.
    for name in ("deploy.sh", "scripts/build.sh"):
        (tmp_path / name).write_text("", encoding="utf-8")
    assert _violations(source)
    with pytest.raises(AssertionError, match="nested/invalid.py"):
        assert_script_boundaries(tmp_path)


@pytest.mark.parametrize("source", [
    "import importlib; importlib.import_module('modules.application.operations_facade')",
    "__import__('modules.application.operations_facade')",
])
def test_dynamic_import_of_stable_facade_is_allowed(source):
    assert _violations(source) == []


@pytest.mark.parametrize("source", [
    "python3 -c \"import importlib; importlib.import_module('modules.services.fake')\"",
    "python3 -c \"__import__('modules.repositories.fake')\"",
    "python3 -c 'from modules.migrations import run_migrations'",
])
def test_nested_shell_dependency_fixture_is_blocked(source, tmp_path):
    nested = tmp_path / "scripts/nested"
    nested.mkdir(parents=True)
    (nested / "invalid.sh").write_text(source, encoding="utf-8")
    (tmp_path / "deploy.sh").write_text("", encoding="utf-8")

    with pytest.raises(AssertionError, match="scripts/nested/invalid.sh"):
        assert_script_boundaries(tmp_path)


def test_root_shell_dependency_fixture_is_blocked(tmp_path):
    (tmp_path / "backup.sh").write_text(
        "python3 -c \"import importlib; "
        "importlib.import_module('modules.repositories.fake')\"",
        encoding="utf-8",
    )
    (tmp_path / "scripts").mkdir()

    with pytest.raises(AssertionError, match="backup.sh"):
        assert_script_boundaries(tmp_path)


@pytest.mark.parametrize("source", [
    "python3 -c \"import importlib; importlib.import_module('modules.application.operations_facade')\"",
    "python3 -c '__import__(\"modules.application.operations_facade\")'",
    "python3 -c 'import json,sys; print(json.load(sys.stdin))'",
])
def test_shell_standard_boundary_fixture_is_allowed(source, tmp_path):
    nested = tmp_path / "scripts/nested"
    nested.mkdir(parents=True)
    (nested / "valid.sh").write_text(source, encoding="utf-8")
    (tmp_path / "deploy.sh").write_text("", encoding="utf-8")

    assert_script_boundaries(tmp_path)
