"""Weekly streak rules and their connection to saved, account-owned activity."""

import re
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

# Importing the app must not access the personal session key.
with patch("configuration.load_secret_key", return_value="streak-test-key"):
    from app import app, local_today

from database import connect_database, save_activity
from progress import calculate_weekly_streaks


def growth_week(start_day, days=5):
    """Build a small set of qualifying dates for a test week."""
    start = date.fromisoformat(start_day)
    return [(start + timedelta(days=offset)).isoformat() for offset in range(days)]


class WeeklyStreakRulesTests(unittest.TestCase):
    def test_empty_or_four_day_week_does_not_start_a_streak(self):
        for dates in ([], growth_week("2026-09-28", 4)):
            with self.subTest(dates=dates):
                self.assertEqual(
                    calculate_weekly_streaks(dates, date(2026, 10, 4)),
                    {"current": 0, "best": 0},
                )

    def test_distinct_dates_count_and_seven_days_still_earn_one_week(self):
        self.assertEqual(
            calculate_weekly_streaks(["2026-09-28"] * 7, date(2026, 10, 4)),
            {"current": 0, "best": 0},
        )
        self.assertEqual(
            calculate_weekly_streaks(growth_week("2026-09-28", 7), date(2026, 10, 4)),
            {"current": 1, "best": 1},
        )

    def test_current_week_extends_streak_as_soon_as_fifth_day_is_reached(self):
        dates = growth_week("2026-09-14") + growth_week("2026-09-21")
        dates += growth_week("2026-09-28")
        self.assertEqual(
            calculate_weekly_streaks(reversed(dates), date(2026, 10, 2)),
            {"current": 3, "best": 3},
        )

    def test_incomplete_week_preserves_run_until_next_monday(self):
        dates = growth_week("2026-09-21") + growth_week("2026-09-28", 4)
        self.assertEqual(
            calculate_weekly_streaks(dates, date(2026, 10, 4)),
            {"current": 1, "best": 1},
        )
        self.assertEqual(
            calculate_weekly_streaks(dates, date(2026, 10, 5)),
            {"current": 0, "best": 1},
        )

    def test_gap_breaks_current_run_but_keeps_older_personal_best(self):
        dates = growth_week("2026-08-31") + growth_week("2026-09-07")
        dates += growth_week("2026-09-14") + growth_week("2026-09-28")
        self.assertEqual(
            calculate_weekly_streaks(dates, date(2026, 10, 4)),
            {"current": 1, "best": 3},
        )

    def test_monday_sunday_boundaries_work_across_new_year(self):
        # Tue-Sat in one week and Wed-Sun in the next; neither needs daily continuity.
        dates = growth_week("2026-12-22") + growth_week("2026-12-30")
        self.assertEqual(
            calculate_weekly_streaks(dates, date(2027, 1, 3)),
            {"current": 2, "best": 2},
        )
        self.assertEqual(
            calculate_weekly_streaks(dates, date(2027, 1, 4)),
            {"current": 2, "best": 2},
        )

    def test_future_saved_dates_cannot_extend_current_or_best_streak(self):
        dates = growth_week("2026-09-21") + growth_week("2026-09-28")
        dates += growth_week("2026-10-05")
        self.assertEqual(
            calculate_weekly_streaks(dates, date(2026, 10, 1)),
            {"current": 1, "best": 1},
        )


class WeeklyStreakDashboardTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database_path = Path(directory.name) / "streaks.sqlite3"
        settings = patch.dict(
            app.config, DATABASE=self.database_path, TESTING=True,
            LOGIN_DISABLED=False, CSRF_ENABLED=False,
        )
        settings.start()
        self.addCleanup(settings.stop)
        clock = patch("app.local_today", return_value=date(2026, 10, 4))
        clock.start()
        self.addCleanup(clock.stop)
        with closing(connect_database(self.database_path)) as connection:
            connection.executemany(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                [("first", "unused-test-hash"), ("second", "unused-test-hash")],
            )
            connection.commit()
        self.client = app.test_client()
        self.sign_in(1)
        self.activity = {
            "activity_date": "2026-09-28", "title": "Balance practice",
            "category": "Fitness", "duration_minutes": "20",
            "what_i_did": "Practised balancing on one leg.",
            "reflection": "Improved my stability.",
        }

    def sign_in(self, user_id):
        with self.client.session_transaction() as session:
            session["user_id"] = user_id

    def save_dates(self, dates, user_id=1):
        return [save_activity(self.database_path, {
            **self.activity, "activity_date": day,
        }, user_id) for day in dates]

    def assert_streak(self, current, best):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="current-streak"', html)
        self.assertRegex(html, rf"\b{current}-week streak\b")
        self.assertIn('id="best-streak"', html)
        noun = "week" if best == 1 else "weeks"
        self.assertIn(f"Personal best: {best} {noun}", html)
        return html

    def test_only_completed_reflected_distinct_days_qualify_including_fitness(self):
        self.save_dates(growth_week("2026-09-28", 4))
        self.save_dates(["2026-09-28"] * 5)
        for reflection in ("\n\t", "\u00a0"):
            save_activity(self.database_path, {
                **self.activity, "activity_date": "2026-10-02", "reflection": reflection,
            }, 1)
        response = self.client.post("/tasks/new", data={
            "title": "Planned walk", "category": "Fitness", "notes": "",
            "planned_date": "2026-10-02", "planned_time": "", "reminder_minutes": "",
        })
        self.assertEqual(response.status_code, 303)
        self.assert_streak(0, 0)
        self.save_dates(["2026-10-02"])
        self.assert_streak(1, 1)

    def test_existing_history_counts_and_accounts_have_separate_streaks(self):
        self.save_dates(growth_week("2026-09-14") + growth_week("2026-09-21"))
        self.save_dates(growth_week("2026-09-28"))
        self.save_dates(growth_week("2026-09-28", 4), user_id=2)
        self.assert_streak(3, 3)
        self.sign_in(2)
        self.assert_streak(0, 0)
        self.save_dates(["2026-10-02"], user_id=2)
        self.assert_streak(1, 1)
        self.sign_in(1)
        self.assert_streak(3, 3)

    def test_backfilled_edits_and_deletions_recalculate_current_and_best(self):
        self.save_dates(growth_week("2026-09-14"))
        self.save_dates(growth_week("2026-09-21", 4))
        self.save_dates(growth_week("2026-09-28"))
        self.assert_streak(1, 1)
        response = self.client.post("/activities/new", data={
            **self.activity, "activity_date": "2026-09-25",
        })
        self.assertEqual(response.status_code, 303)
        activity_id = int(re.search(r"/activities/(\d+)/saved", response.location).group(1))
        self.assert_streak(3, 3)

        for day, expected in (("2026-09-24", 1), ("2026-09-25", 3)):
            response = self.client.post(f"/activities/{activity_id}/edit", data={
                **self.activity, "activity_date": day,
            })
            self.assertEqual(response.status_code, 303)
            self.assert_streak(expected, expected)

        duplicate_id = self.save_dates(["2026-09-25"])[0]
        for deleted_id, expected in ((activity_id, 3), (duplicate_id, 1)):
            confirmation = self.client.get(f"/activities/{deleted_id}/delete")
            token = re.search(
                r'name="confirmation_token" value="([a-f0-9]+)"',
                confirmation.get_data(as_text=True),
            ).group(1)
            response = self.client.post(f"/activities/{deleted_id}/delete", data={
                "confirmation_token": token,
            })
            self.assertEqual(response.status_code, 303)
            self.assert_streak(expected, expected)

    def test_saved_future_dates_are_excluded_from_dashboard_history(self):
        self.save_dates(growth_week("2026-09-28"))
        self.save_dates(growth_week("2026-10-05"))
        self.assert_streak(1, 1)
        with patch("app.local_today", return_value=date(2026, 10, 1)):
            self.assert_streak(0, 0)

    def test_streak_rollover_uses_monday_in_dar_es_salaam(self):
        self.save_dates(growth_week("2026-09-21"))
        self.save_dates(growth_week("2026-09-28", 4))
        for instant, expected in (
            (datetime(2026, 10, 4, 20, 59, tzinfo=timezone.utc), 1),
            (datetime(2026, 10, 4, 21, 0, tzinfo=timezone.utc), 0),
        ):
            with self.subTest(instant=instant):
                with patch("app.local_today", wraps=local_today), patch("app.datetime") as clock:
                    clock.now.side_effect = lambda zone: instant.astimezone(zone)
                    self.assert_streak(expected, 1)


if __name__ == "__main__":
    unittest.main()
