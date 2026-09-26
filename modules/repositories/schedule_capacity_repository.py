"""Backward-compatible facade for the split schedule repositories.

New code should depend on the repository matching its responsibility. Existing
callers continue to use ScheduleCapacityRepository while methods are migrated.
"""

from functools import wraps

from modules.repositories.schedule_evidence_repository import ScheduleEvidenceRepository
from modules.repositories.schedule_planning_repository import SchedulePlanningRepository
from modules.repositories.schedule_revision_repository import ScheduleRevisionRepository


class ScheduleCapacityRepository:
    """Compatibility facade delegating to the schedule-specific repositories."""


def _delegate(repository, name):
    target = getattr(repository, name)

    @wraps(target)
    def delegated(*args, **kwargs):
        return getattr(repository, name)(*args, **kwargs)

    return staticmethod(delegated)


for _repository in (
    SchedulePlanningRepository,
    ScheduleRevisionRepository,
    ScheduleEvidenceRepository,
):
    for _name, _descriptor in vars(_repository).items():
        if isinstance(_descriptor, staticmethod):
            setattr(ScheduleCapacityRepository, _name, _delegate(_repository, _name))
