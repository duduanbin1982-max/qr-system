import ast
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IGNORED_PARTS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "backups",
    "data",
    "dist",
    "logs",
    "node_modules",
    "ssl_backup",
    "uploads",
}


def _source_files():
    for path in PROJECT_ROOT.rglob("*.py"):
        relative_parts = set(path.relative_to(PROJECT_ROOT).parts)
        if not relative_parts.intersection(IGNORED_PARTS):
            yield path


def _module_map():
    modules = {}
    packages = set()
    for path in _source_files():
        relative = path.relative_to(PROJECT_ROOT).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            module_name = ".".join(parts[:-1])
            packages.add(module_name)
        else:
            module_name = ".".join(parts)
        modules[path] = module_name
    return modules, packages


def _resolve_internal_import(name, known_modules):
    if not (name == "modules" or name.startswith("modules.")):
        return None
    parts = name.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in known_modules:
            return candidate
        parts.pop()
    return None


def _dependency_graph():
    modules, packages = _module_map()
    known_modules = set(modules.values()) | packages
    graph = defaultdict(set)

    for path, source_module in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
        for node in ast.walk(tree):
            import_names = []
            if isinstance(node, ast.Import):
                import_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                base_module = node.module
                if node.level:
                    package_parts = source_module.split(".")[: -node.level]
                    base_module = ".".join(package_parts + [node.module])
                import_names.append(base_module)
                for alias in node.names:
                    imported_module = f"{base_module}.{alias.name}"
                    if imported_module in known_modules:
                        import_names.append(imported_module)

            for import_name in import_names:
                target_module = _resolve_internal_import(import_name, known_modules)
                if target_module and target_module != source_module:
                    graph[source_module].add(target_module)

    return graph, known_modules


def _strongly_connected_components(graph, known_modules):
    indices = {}
    lowlinks = {}
    stack = []
    on_stack = set()
    components = []

    def visit(module_name):
        indices[module_name] = len(indices)
        lowlinks[module_name] = indices[module_name]
        stack.append(module_name)
        on_stack.add(module_name)

        for dependency in graph.get(module_name, ()):
            if dependency not in indices:
                visit(dependency)
                lowlinks[module_name] = min(lowlinks[module_name], lowlinks[dependency])
            elif dependency in on_stack:
                lowlinks[module_name] = min(lowlinks[module_name], indices[dependency])

        if lowlinks[module_name] == indices[module_name]:
            component = []
            while True:
                dependency = stack.pop()
                on_stack.remove(dependency)
                component.append(dependency)
                if dependency == module_name:
                    break
            if len(component) > 1:
                components.append(sorted(component))

    for module_name in sorted(known_modules):
        if module_name not in indices:
            visit(module_name)

    return components


def test_backend_modules_have_no_import_cycles():
    graph, known_modules = _dependency_graph()
    cycles = _strongly_connected_components(graph, known_modules)

    assert cycles == []

