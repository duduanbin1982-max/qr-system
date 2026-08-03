"""Production reporting-day boundaries."""
from datetime import datetime, timedelta


REPORTING_DAY_START_HOUR = 7


def reporting_day_bounds(reporting_date):
    start = datetime.strptime(reporting_date, "%Y-%m-%d").replace(
        hour=REPORTING_DAY_START_HOUR,
    )
    end = start + timedelta(days=1)
    return (
        start.strftime("%Y-%m-%d %H:%M:%S"),
        end.strftime("%Y-%m-%d %H:%M:%S"),
    )


def reporting_range_bounds(start="", end=""):
    """Return the half-open timestamps covered by reporting-day dates."""
    start_date = datetime.strptime(start, "%Y-%m-%d") if start else None
    end_date = datetime.strptime(end, "%Y-%m-%d") if end else None
    if start_date and end_date and start_date > end_date:
        raise ValueError("start date must not be after end date")

    period_start = None
    period_end = None
    if start_date:
        period_start = start_date.replace(hour=REPORTING_DAY_START_HOUR)
    if end_date:
        period_end = end_date.replace(hour=REPORTING_DAY_START_HOUR) + timedelta(days=1)
    return (
        period_start.strftime("%Y-%m-%d %H:%M:%S") if period_start else None,
        period_end.strftime("%Y-%m-%d %H:%M:%S") if period_end else None,
    )


def current_reporting_day(now=None):
    current = now or datetime.now()
    if current.hour < REPORTING_DAY_START_HOUR:
        current -= timedelta(days=1)
    return current.strftime("%Y-%m-%d")
