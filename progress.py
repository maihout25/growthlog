"""Calculate weekly streaks from saved growth dates, without storing counters."""

from datetime import date, timedelta


def calculate_weekly_streaks(growth_dates, today, goal=5):
    """Return current and best runs of consecutive weeks meeting the day goal."""
    days_by_week = {}
    for value in growth_dates:
        activity_date = date.fromisoformat(value)
        if activity_date > today:
            continue
        monday = activity_date - timedelta(days=activity_date.weekday())
        days_by_week.setdefault(monday, set()).add(activity_date)

    successful_weeks = sorted(
        monday for monday, days in days_by_week.items() if len(days) >= goal
    )
    this_monday = today - timedelta(days=today.weekday())
    previous_monday = None
    run = current = best = 0

    for monday in successful_weeks:
        if previous_monday is not None and (monday - previous_monday).days == 7:
            run += 1
        else:
            run = 1
        best = max(best, run)

        # This week may still be in progress. Keep a run ending last week alive
        # until this week ends, or extend it as soon as this week meets the goal.
        if (this_monday - monday).days in (0, 7):
            current = run
        previous_monday = monday

    return {"current": current, "best": best}
