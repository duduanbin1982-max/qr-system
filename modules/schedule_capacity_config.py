"""Single source of truth for process scheduling capacity defaults.

The legacy ``production_lines`` table represents order-level line assignment.
Capacity-aware scheduling uses ``process_production_lines`` exclusively; these
defaults provision that process-scoped pool and are intentionally kept in one
module so migrations and runtime code cannot drift apart.
"""

DEFAULT_DAILY_MINUTES = 480

DEFAULT_PROCESS_LINE_COUNTS = {
    "下料": 1,
    "铆接": 4,
    "焊接": 10,
    "抛丸": 1,
    "打磨": 1,
    "镗孔": 2,
    "喷漆": 2,
}
