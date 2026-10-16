"""Normalize conflict facts once, retaining the original interval-pair identity."""

from modules.domain.production_time import parse_database_timestamp
from modules.domain.schedule_planning import ConflictDetectionSnapshot


def resource_key(fact):
    node_id = fact.get("production_node_id")
    if node_id not in (None, ""):
        return "node", int(node_id)
    line_id = fact.get("process_line_id")
    if line_id not in (None, ""):
        return "legacy_line", int(line_id)
    return None


def interval_overlap(first, second):
    start = max(first["_start"], second["_start"])
    end = min(first["_end"], second["_end"])
    if start >= end:
        return None
    return start, end, max(int((end - start).total_seconds() / 60), 1)


def _normalize_intervals(source):
    valid, invalid = [], []
    for raw in source or ():
        fact = dict(raw)
        start = parse_database_timestamp(fact.get("start_at"))
        end = parse_database_timestamp(fact.get("end_at"))
        key = resource_key(fact)
        if start is None or end is None or end <= start or key is None:
            invalid.append(fact)
            continue
        fact.update(_start=start, _end=end, _resource_key=key)
        valid.append(fact)
    return valid, invalid


def build_conflict_snapshot(*, candidate_intervals=(), occupied_intervals=(),
                            unavailable_intervals=(), operations=()):
    candidate, invalid = _normalize_intervals(candidate_intervals)
    occupied, _ = _normalize_intervals(occupied_intervals)
    # Capture dict equality before tuple/list values become equally frozen.
    # Each fact's first matching candidate index preserves the original
    # `second in candidate` / `candidate.index(second)` suppression rule.
    positions = tuple(
        next((index for index, candidate_fact in enumerate(candidate)
              if candidate_fact == fact), None)
        for fact in candidate + occupied
    )
    unavailable, _ = _normalize_intervals(unavailable_intervals)
    return ConflictDetectionSnapshot(
        candidate_intervals=tuple(candidate), occupied_intervals=tuple(occupied),
        unavailable_intervals=tuple(unavailable),
        invalid_candidate_intervals=tuple(invalid),
        operations=tuple(dict(item) for item in (operations or ())),
        equal_candidate_positions=positions,
    )
