import re
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app import app, local_today
from database import save_activity


class ProgressTests(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.database_path = Path(temporary_directory.name) / "progress.sqlite3"
        settings = patch.dict(
            app.config, DATABASE=self.database_path, TESTING=True,
            LOGIN_DISABLED=True, CSRF_ENABLED=False,
        )
        settings.start()
        self.addCleanup(settings.stop)
        today = patch("app.local_today", return_value=date(2026, 10, 4))  # Sunday
        today.start()
        self.addCleanup(today.stop)
        self.client = app.test_client()
        self.activity = {
            "activity_date": "2026-09-28",
            "title": "Growth practice",
            "category": "Fitness",
            "duration_minutes": "20",
            "what_i_did": "Practised balance.",
            "reflection": "Improved my stability.",
        }

    def assert_progress(self, count):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        noun = "day" if count == 1 else "days"
        self.assertIn(f"{count} growth {noun} this week".encode(), response.data)
        return response.get_data(as_text=True)

    def test_empty_week_shows_zero_and_room_for_rest(self):
        html = self.assert_progress(0)
        self.assertIn('datetime="2026-09-28"', html)
        self.assertIn('datetime="2026-10-04"', html)
        self.assertEqual(html.count('<li class="week-day'), 7)
        self.assertIn("Rest days belong here", html)
        self.assertIn('value="0" max="5"', html)

    def test_multiple_activities_on_one_date_count_once_and_fitness_counts(self):
        for category in ("Reading", "Coding", "Fitness", "Other"):
            save_activity(self.database_path, {**self.activity, "category": category})
        self.assert_progress(1)
        save_activity(self.database_path, {**self.activity, "activity_date": "2026-09-29"})
        self.assert_progress(2)

    def test_monday_and_sunday_included_adjacent_weeks_excluded(self):
        for day in ("2026-09-27", "2026-09-28", "2026-10-04", "2026-10-05"):
            save_activity(self.database_path, {**self.activity, "activity_date": day})
        self.assert_progress(2)
        with patch("app.local_today", return_value=date(2026, 10, 5)):
            html = self.assert_progress(1)
            self.assertIn('datetime="2026-10-05"', html)
            self.assertIn('datetime="2026-10-11"', html)

    def test_week_can_cross_a_year_boundary(self):
        for day in ("2026-12-27", "2026-12-28", "2027-01-03", "2027-01-04"):
            save_activity(self.database_path, {**self.activity, "activity_date": day})
        with patch("app.local_today", return_value=date(2027, 1, 3)):
            html = self.assert_progress(2)
            self.assertIn('datetime="2026-12-28"', html)
            self.assertIn('datetime="2027-01-03"', html)

    def test_future_saved_dates_do_not_count_before_they_occur(self):
        # Direct fixtures bypass the form's existing future-date validation.
        for day in ("2026-09-28", "2026-09-29", "2026-09-30"):
            save_activity(self.database_path, {**self.activity, "activity_date": day})
        with patch("app.local_today", return_value=date(2026, 9, 29)):
            html = self.assert_progress(2)
            self.assertEqual(html.count("Upcoming"), 5)

    def test_whitespace_reflections_do_not_qualify(self):
        # The form rejects these. Check the dashboard also handles saved whitespace.
        for reflection in ("\n\t", "\u00a0"):
            save_activity(self.database_path, {**self.activity, "reflection": reflection})
        self.assert_progress(0)
        save_activity(self.database_path, self.activity)
        self.assert_progress(1)

    def test_five_to_seven_days_show_goal_met_without_overfilling_bar(self):
        monday = date(2026, 9, 28)
        for offset in range(7):
            save_activity(self.database_path, {
                **self.activity, "activity_date": (monday + timedelta(days=offset)).isoformat(),
            })
            if offset >= 4:
                html = self.assert_progress(offset + 1)
                self.assertIn('value="5" max="5"', html)
                self.assertIn("You reached your five-day goal", html)

    def test_edits_and_deletions_recalculate_from_saved_records(self):
        response = self.client.post("/activities/new", data=self.activity)
        self.assertEqual(response.status_code, 303)
        first_id = int(re.search(r"/activities/(\d+)/saved", response.location).group(1))
        second_id = save_activity(self.database_path, self.activity)
        self.assert_progress(1)

        response = self.client.post(f"/activities/{second_id}/edit", data={
            **self.activity, "activity_date": "2026-09-29",
        })
        self.assertEqual(response.status_code, 303)
        self.assert_progress(2)

        # Move it into the previous week, then back onto the first activity's date.
        for day in ("2026-09-27", "2026-09-28"):
            response = self.client.post(f"/activities/{second_id}/edit", data={
                **self.activity, "activity_date": day,
            })
            self.assertEqual(response.status_code, 303)
            self.assert_progress(1)

        # Removing one entry keeps the day; removing the last entry removes the day.
        for activity_id, expected in ((first_id, 1), (second_id, 0)):
            confirmation = self.client.get(f"/activities/{activity_id}/delete")
            token = re.search(
                r'name="confirmation_token" value="([a-f0-9]+)"',
                confirmation.get_data(as_text=True),
            ).group(1)
            response = self.client.post(f"/activities/{activity_id}/delete", data={
                "confirmation_token": token,
            })
            self.assertEqual(response.status_code, 303)
            self.assert_progress(expected)

    def test_dashboard_rolls_into_monday_using_dar_es_salaam_time(self):
        save_activity(self.database_path, {**self.activity, "activity_date": "2026-09-27"})
        save_activity(self.database_path, self.activity)
        # Still Sunday in UTC, but already Monday in Tanzania.
        instant = datetime(2026, 9, 27, 21, 30, tzinfo=timezone.utc)
        with patch("app.local_today", wraps=local_today), patch("app.datetime") as clock:
            clock.now.side_effect = lambda zone: instant.astimezone(zone)
            html = self.assert_progress(1)
            self.assertIn('datetime="2026-09-28" aria-current="date"', html)
            self.assertIn('datetime="2026-10-04"', html)


if __name__ == "__main__":
    unittest.main()
