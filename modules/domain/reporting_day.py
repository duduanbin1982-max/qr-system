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


def current_reporting_day(now=None):
    current = now or datetime.now()
    if current.hour < REPORTING_DAY_START_HOUR:
        current -= timedelta(days=1)
    return current.strftime("%Y-%m-%d")
