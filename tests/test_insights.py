import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app import app
from database import connect_database, delete_activity, save_activity, update_activity


class InsightsTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_path = Path(self.temporary_directory.name) / "test.sqlite3"
        settings = patch.dict(
            app.config, DATABASE=self.database_path, TESTING=True,
            CSRF_ENABLED=True, LOGIN_DISABLED=False,
        )
        settings.start()
        self.addCleanup(settings.stop)
        today = patch("insights.local_today", return_value=date(2026, 9, 30))
        today.start()
        self.addCleanup(today.stop)
        with closing(connect_database(self.database_path)) as connection:
            connection.execute("INSERT INTO users (id, username, password_hash) VALUES (1, 'first', 'unused')")
            connection.execute("INSERT INTO users (id, username, password_hash) VALUES (2, 'second', 'unused')")
            connection.commit()
        self.client = app.test_client()
        self.sign_in(1)
        self.activity = {
            "activity_date": "2026-09-28", "title": "Practised squats", "category": "Fitness",
            "duration_minutes": "20", "what_i_did": "Completed three sets.",
            "reflection": "Improved my balance.",
        }
        self.activity_id = save_activity(self.database_path, self.activity, user_id=1)
        self.fitness_url = f"/activities/{self.activity_id}/fitness"
        self.workout = {
            "exercise_type": "Squats", "sets": "3", "reps": "12", "weight_kg": "5.5",
            "distance_km": "0", "notes": "Slow and steady.",
        }
        self.week_url = "/reflections/2026-09-28"
        self.reflection = {"wins": "Kept showing up.", "challenges": "Needed more sleep.", "next_week": "Allow rest."}

    def sign_in(self, user_id):
        with self.client.session_transaction() as session:
            session.clear()
            session["user_id"] = user_id
            session["csrf_token"] = "insights-test-token"

    def post(self, url, data=None, **kwargs):
        return self.client.post(url, data={**(data or {}), "csrf_token": "insights-test-token"}, **kwargs)

    def fetch(self, query, parameters=()):
        with closing(connect_database(self.database_path)) as connection:
            return connection.execute(query, parameters).fetchall()

    def test_workout_round_trip_updates_one_record_and_keeps_activity(self):
        self.assertEqual(self.client.get(self.fitness_url).status_code, 200)
        self.assertEqual(self.post(self.fitness_url, self.workout).status_code, 303)
        page = self.client.get(self.fitness_url)
        self.assertIn(b'value="5.5"', page.data)
        self.assertIn(b"Slow and steady.", page.data)
        self.assertEqual(self.post(self.fitness_url, {**self.workout, "sets": "4"}).status_code, 303)
        rows = self.fetch("SELECT * FROM fitness_details")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sets"], 4)
        self.assertEqual(rows[0]["weight_kg"], 5.5)
        self.assertEqual(self.fetch("SELECT reflection FROM activities")[0]["reflection"], self.activity["reflection"])

    def test_invalid_workout_preserves_existing_details_and_input(self):
        self.post(self.fitness_url, self.workout)
        cases = [
            ("sets", "0"), ("sets", "1.5"), ("sets", str(2**64)), ("reps", "-1"),
            ("reps", "twelve"), ("weight_kg", "-1"), ("weight_kg", "nan"),
            ("weight_kg", "inf"), ("distance_km", "-0.1"), ("distance_km", "1e999"),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                response = self.post(self.fitness_url, {**self.workout, field: value, "notes": "Please keep my text."})
                self.assertEqual(response.status_code, 400)
                self.assertIn(b"Please keep my text.", response.data)
                self.assertEqual(self.fetch("SELECT sets FROM fitness_details")[0]["sets"], 3)

    def test_blank_workout_clears_only_optional_details(self):
        self.post(self.fitness_url, self.workout)
        self.assertEqual(self.post(self.fitness_url).status_code, 303)
        self.assertEqual(self.fetch("SELECT * FROM fitness_details"), [])
        self.assertEqual(len(self.fetch("SELECT * FROM activities")), 1)

    def test_optional_measurements_can_be_blank_or_zero(self):
        self.assertEqual(self.post(self.fitness_url, {"weight_kg": "0", "notes": "Bodyweight exercise"}).status_code, 303)
        row = self.fetch("SELECT * FROM fitness_details")[0]
        self.assertIsNone(row["sets"])
        self.assertIsNone(row["distance_km"])
        self.assertEqual(row["weight_kg"], 0)

    def test_fitness_requires_owned_fitness_activity(self):
        other_id = save_activity(self.database_path, self.activity, user_id=2)
        reading_id = save_activity(self.database_path, {**self.activity, "category": "Reading"}, user_id=1)
        for activity_id in (other_id, reading_id, 999):
            url = f"/activities/{activity_id}/fitness"
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.post(url, self.workout).status_code, 404)
        self.assertEqual(self.fetch("SELECT * FROM fitness_details"), [])

    def test_workout_details_are_removed_when_activity_is_deleted(self):
        self.post(self.fitness_url, self.workout)
        delete_activity(self.database_path, self.activity_id, user_id=1)
        self.assertEqual(self.fetch("SELECT * FROM fitness_details"), [])

    def test_reflections_save_edit_and_list_without_duplicates(self):
        self.assertEqual(self.client.get(self.week_url).status_code, 200)
        self.assertEqual(self.post(self.week_url, self.reflection).status_code, 303)
        self.assertEqual(self.post(self.week_url, {**self.reflection, "wins": "Changed my reflection."}).status_code, 303)
        page = self.client.get("/reflections")
        self.assertIn(b"Changed my reflection.", page.data)
        rows = self.fetch("SELECT * FROM weekly_reflections")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["week_start"], "2026-09-28")
        self.assertEqual(rows[0]["wins"], "Changed my reflection.")

    def test_blank_reflection_is_rejected_without_overwriting(self):
        self.post(self.week_url, self.reflection)
        self.assertEqual(self.post(self.week_url, {"wins": " \n "}).status_code, 400)
        self.assertEqual(self.fetch("SELECT wins FROM weekly_reflections")[0]["wins"], self.reflection["wins"])
        self.assertEqual(self.post("/reflections/2026-09-21", {"next_week": "A smaller step."}).status_code, 303)

    def test_future_or_non_monday_reflection_urls_are_rejected(self):
        for week in ("2026-10-05", "2026-09-29", "2026-02-30", "20260928", "2026-W40-1", "bad"):
            with self.subTest(week=week):
                self.assertEqual(self.client.get(f"/reflections/{week}").status_code, 404)
                self.assertEqual(self.post(f"/reflections/{week}", self.reflection).status_code, 404)
        self.assertEqual(self.fetch("SELECT * FROM weekly_reflections"), [])

    def test_week_picker_finds_monday_and_rejects_future_week(self):
        response = self.client.get("/reflections?week=2026-09-23")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/reflections/2026-09-21"))
        self.assertEqual(self.client.get("/reflections?week=2026-10-05").status_code, 400)
        self.assertEqual(self.client.get("/reflections?week=invalid").status_code, 400)

    def test_week_summary_counts_distinct_owned_dates_and_refreshes_after_changes(self):
        second_id = save_activity(self.database_path, {**self.activity, "category": "Reading"}, user_id=1)
        save_activity(self.database_path, {**self.activity, "activity_date": "2026-09-29"}, user_id=2)
        save_activity(self.database_path, {**self.activity, "activity_date": "2026-10-01"}, user_id=1)
        page = self.client.get(self.week_url)
        self.assertIn(b"1 of 5 growth days", page.data)
        self.assertIn(b"2 completed activities", page.data)
        update_activity(self.database_path, second_id, {**self.activity, "activity_date": "2026-09-30"}, user_id=1)
        self.assertIn(b"2 of 5 growth days", self.client.get(self.week_url).data)
        delete_activity(self.database_path, second_id, user_id=1)
        self.assertIn(b"1 of 5 growth days", self.client.get(self.week_url).data)

    def test_reflections_are_private_and_same_week_can_belong_to_two_accounts(self):
        self.post(self.week_url, self.reflection)
        self.sign_in(2)
        self.assertNotIn(self.reflection["wins"].encode(), self.client.get("/reflections").data)
        self.assertNotIn(self.reflection["wins"].encode(), self.client.get(self.week_url).data)
        self.assertEqual(self.client.get(self.week_url + "/delete").status_code, 404)
        self.assertEqual(self.post(self.week_url + "/delete", {"confirm": "delete"}).status_code, 404)
        self.post(self.week_url, {"wins": "My own reflection."})
        rows = self.fetch("SELECT user_id, wins FROM weekly_reflections ORDER BY user_id")
        self.assertEqual([(row["user_id"], row["wins"]) for row in rows], [(1, self.reflection["wins"]), (2, "My own reflection.")])

    def test_reflection_delete_requires_confirmation_and_keeps_activities(self):
        self.post(self.week_url, self.reflection)
        self.assertEqual(self.client.get(self.week_url + "/delete").status_code, 200)
        self.client.get(self.week_url)  # Following Cancel only reads the page.
        self.assertEqual(len(self.fetch("SELECT * FROM weekly_reflections")), 1)
        self.assertEqual(self.post(self.week_url + "/delete").status_code, 400)
        self.assertEqual(self.post(self.week_url + "/delete", {"confirm": "delete"}).status_code, 303)
        self.assertEqual(self.fetch("SELECT * FROM weekly_reflections"), [])
        self.assertEqual(len(self.fetch("SELECT * FROM activities")), 1)

    def test_csrf_is_required_for_workout_and_reflection_writes(self):
        self.post(self.week_url, self.reflection)
        for url, data in ((self.fitness_url, self.workout), (self.week_url, self.reflection), (self.week_url + "/delete", {"confirm": "delete"})):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data=data).status_code, 400)
        self.assertEqual(self.fetch("SELECT * FROM fitness_details"), [])
        self.assertEqual(len(self.fetch("SELECT * FROM weekly_reflections")), 1)

    def test_saved_text_is_escaped(self):
        text = "<script>alert('example')</script>"
        self.post(self.fitness_url, {"notes": text})
        self.post(self.week_url, {"wins": text})
        for url in (self.fitness_url, self.week_url, "/reflections", self.week_url + "/delete"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertIn(b"&lt;script&gt;", response.data)
                self.assertNotIn(text.encode(), response.data)


if __name__ == "__main__":
    unittest.main()
