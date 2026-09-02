"""Pure validation and planning policies for the linear SQLite schema history."""

from collections import defaultdict


def linear_dependencies(migrations):
    """Build an explicit predecessor dependency for a linear migration sequence."""
    versions = sorted(version for version, _, _ in migrations)
    return {
        version: (() if index == 0 else (versions[index - 1],))
        for index, version in enumerate(versions)
    }


def validate_registry(migrations, dependencies):
    """Validate migration identities, dependency references, and acyclicity."""
    ordered = sorted(migrations, key=lambda migration: migration[0])
    versions = [migration[0] for migration in ordered]
    if len(versions) != len(set(versions)):
        raise RuntimeError("duplicate database migration versions registered")
    if any(not isinstance(version, int) or version <= 0 for version in versions):
        raise RuntimeError("database migration versions must be positive integers")
    for version, description, migration_fn in ordered:
        if not isinstance(description, str) or not description.strip():
            raise RuntimeError(f"database migration v{version} has no description")
        if not callable(migration_fn):
            raise RuntimeError(f"database migration v{version} is not callable")

    version_set = set(versions)
    dependency_keys = set(dependencies)
    if dependency_keys != version_set:
        missing = sorted(version_set - dependency_keys)
        extra = sorted(dependency_keys - version_set)
        raise RuntimeError(
            f"migration dependency catalog mismatch: missing={missing}, extra={extra}"
        )

    dependents = defaultdict(list)
    remaining = {}
    for version in versions:
        declared = tuple(dependencies[version])
        if len(declared) != len(set(declared)):
            raise RuntimeError(f"database migration v{version} repeats a dependency")
        unknown = sorted(set(declared) - version_set)
        if unknown:
            raise RuntimeError(
                f"database migration v{version} has unknown dependencies: {unknown}"
            )
        non_predecessors = sorted(
            dependency for dependency in declared if dependency >= version
        )
        if non_predecessors:
            raise RuntimeError(
                f"database migration v{version} depends on non-predecessors: "
                f"{non_predecessors}"
            )
        remaining[version] = len(declared)
        for dependency in declared:
            dependents[dependency].append(version)

    ready = sorted(version for version, count in remaining.items() if count == 0)
    topological_versions = []
    while ready:
        version = ready.pop(0)
        topological_versions.append(version)
        for dependent in sorted(dependents[version]):
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                ready.append(dependent)
                ready.sort()
    if len(topological_versions) != len(versions):
        cyclic = sorted(version for version, count in remaining.items() if count > 0)
        raise RuntimeError(f"cyclic database migration dependencies: {cyclic}")

    by_version = {version: (description, fn) for version, description, fn in ordered}
    return [
        (version, by_version[version][0], by_version[version][1])
        for version in topological_versions
    ]


def plan_migrations(current_version, migrations, dependencies):
    """Return the validated, dependency-ordered migrations after current_version."""
    ordered = validate_registry(migrations, dependencies)
    latest = max((version for version, _, _ in ordered), default=0)
    if current_version < 0:
        raise RuntimeError("database user_version cannot be negative")
    if current_version > latest:
        raise RuntimeError(
            f"database schema v{current_version} is newer than application schema v{latest}"
        )

    completed = {version for version, _, _ in ordered if version <= current_version}
    pending = []
    for migration in ordered:
        version = migration[0]
        if version <= current_version:
            continue
        unsatisfied = sorted(set(dependencies[version]) - completed)
        if unsatisfied:
            raise RuntimeError(
                f"database migration v{version} has unsatisfied dependencies: {unsatisfied}"
            )
        pending.append(migration)
        completed.add(version)
    return pending
