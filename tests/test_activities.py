import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app import LOCAL_TIMEZONE, app, local_today
from database import get_activity, list_activities, save_activity


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_path = Path(self.temporary_directory.name) / "test.sqlite3"
        self.settings = patch.dict(
            app.config, DATABASE=self.database_path, TESTING=True,
            LOGIN_DISABLED=True, CSRF_ENABLED=False,
        )
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.today = patch("app.local_today", return_value=date(2026, 9, 28))
        self.today.start()
        self.addCleanup(self.today.stop)
        self.client = app.test_client()
        self.activity = {
            "activity_date": "2026-09-28",
            "title": "Practised squats",
            "category": "Fitness",
            "duration_minutes": "20",
            "what_i_did": "Completed three sets.",
            "reflection": "Improved my balance.",
        }

    def test_form_defaults_to_local_today(self):
        response = self.client.get("/activities/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'value="2026-09-28"', response.data)
        self.assertIn(b'max="2026-09-28"', response.data)

    def test_save_persists_and_refresh_does_not_duplicate(self):
        response = self.client.post("/activities/new", data=self.activity)
        self.assertEqual(response.status_code, 303)
        # A new client and new database connections can still read the saved row.
        fresh_client = app.test_client()
        for _ in range(2):
            saved = fresh_client.get(response.location)
            self.assertEqual(saved.status_code, 200)
            self.assertIn(b"Improved my balance.", saved.data)
        with closing(sqlite3.connect(self.database_path)) as connection:
            rows = connection.execute(
                "SELECT activity_date, title, category, duration_minutes, what_i_did, reflection FROM activities"
            ).fetchall()
        self.assertEqual(rows, [(
            "2026-09-28", "Practised squats", "Fitness", 20,
            "Completed three sets.", "Improved my balance.",
        )])

    def test_invalid_submissions_are_not_saved_and_keep_entered_title(self):
        cases = [
            ("activity_date", "2026-09-29"),
            ("activity_date", "2026-02-30"),
            ("activity_date", ""),
            ("category", "Planned task"),
            ("duration_minutes", "0"),
            ("duration_minutes", "-5"),
            ("duration_minutes", "1.5"),
            ("duration_minutes", "1441"),
            ("duration_minutes", "lots"),
            ("what_i_did", "  "),
            ("reflection", " \n "),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                response = self.client.post(
                    "/activities/new", data={**self.activity, field: value}
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(b"Practised squats", response.data)
        self.assertFalse(self.database_path.exists())
        self.assertEqual(self.client.post("/activities/new", data={}).status_code, 400)

    def test_past_date_and_quoted_text_are_saved_as_text(self):
        self.activity.update(activity_date="2026-09-27", title="  Reader's <script>notes</script>  ")
        response = self.client.post("/activities/new", data=self.activity, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"&lt;script&gt;notes&lt;/script&gt;", response.data)
        self.assertNotIn(b"<script>", response.data)

    def test_missing_activity_returns_404(self):
        self.assertEqual(self.client.get("/activities/999/saved").status_code, 404)

    def test_edit_form_loads_saved_values_without_changing_record(self):
        activity_id = save_activity(self.database_path, self.activity)
        before = dict(get_activity(self.database_path, activity_id))
        response = self.client.get(f"/activities/{activity_id}/edit")
        self.assertEqual(response.status_code, 200)
        for value in self.activity.values():
            self.assertIn(value.encode(), response.data)
        self.assertIn(b'value="Fitness" selected', response.data)
        self.assertIn(f'action="/activities/{activity_id}/edit"'.encode(), response.data)
        self.assertIn(b"Save changes", response.data)
        self.assertIn(b"Cancel and return to journal", response.data)
        self.client.get("/journal")
        self.assertEqual(dict(get_activity(self.database_path, activity_id)), before)

    def test_edit_updates_only_chosen_row_and_journal_order(self):
        activity_id = save_activity(self.database_path, self.activity)
        other_id = save_activity(self.database_path, {**self.activity, "title": "Other activity"})
        other_before = dict(get_activity(self.database_path, other_id))
        edited = {
            "activity_date": "2026-09-20",
            "title": "Reader's <script>notes</script>",
            "category": "Reading",
            "duration_minutes": "30",
            "what_i_did": "Read a chapter.\nMade notes.",
            "reflection": "Learned about consistency.",
        }
        response = self.client.post(
            f"/activities/{activity_id}/edit", data={**edited, "id": str(other_id)}
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith(f"/activities/{activity_id}/saved"))
        expected = {**edited, "id": activity_id, "duration_minutes": 30, "user_id": None}
        self.assertEqual(dict(get_activity(self.database_path, activity_id)), expected)
        self.assertEqual(dict(get_activity(self.database_path, other_id)), other_before)
        # Refreshing the confirmation reads the record; it does not create a copy.
        for _ in range(2):
            self.assertEqual(self.client.get(response.location).status_code, 200)
        self.assertEqual([row["id"] for row in list_activities(self.database_path)], [other_id, activity_id])
        journal = self.client.get("/journal").get_data(as_text=True)
        self.assertLess(journal.index(f'id="activity-{other_id}"'), journal.index(f'id="activity-{activity_id}"'))
        self.assertIn("Learned about consistency.", journal)
        self.assertIn("&lt;script&gt;notes&lt;/script&gt;", journal)
        self.assertNotIn("<script>", journal)

    def test_invalid_edits_preserve_saved_record_and_submitted_form(self):
        activity_id = save_activity(self.database_path, self.activity)
        before = dict(get_activity(self.database_path, activity_id))
        cases = [
            ("activity_date", "2026-09-29"),
            ("activity_date", "2026-02-30"),
            ("title", "  "),
            ("category", "Planned task"),
            ("duration_minutes", "0"),
            ("duration_minutes", "1.5"),
            ("what_i_did", "  "),
            ("reflection", " \n "),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                response = self.client.post(
                    f"/activities/{activity_id}/edit",
                    data={**self.activity, "title": "Unsaved revision", field: value},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(f'action="/activities/{activity_id}/edit"'.encode(), response.data)
                if field != "title":
                    self.assertIn(b"Unsaved revision", response.data)
                self.assertEqual(dict(get_activity(self.database_path, activity_id)), before)

    def test_edit_missing_activity_returns_404_without_creating_row(self):
        self.assertEqual(self.client.get("/activities/999/edit").status_code, 404)
        response = self.client.post("/activities/999/edit", data=self.activity)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(list_activities(self.database_path), [])

    def test_dar_es_salaam_date_changes_at_local_midnight(self):
        # Tanzania is already on Tuesday while UTC is still on Monday.
        instant = datetime(2026, 9, 28, 21, 30, tzinfo=timezone.utc)
        with patch("app.datetime") as clock:
            clock.now.side_effect = lambda zone: instant.astimezone(zone)
            self.assertEqual(local_today(), date(2026, 9, 29))
            clock.now.assert_called_once_with(LOCAL_TIMEZONE)

    def get_delete_token(self, activity_id):
        response = self.client.get(f"/activities/{activity_id}/delete")
        self.assertEqual(response.status_code, 200)
        return re.search(
            r'name="confirmation_token" value="([a-f0-9]+)"',
            response.get_data(as_text=True),
        ).group(1)

    def test_delete_confirmation_and_cancel_keep_saved_record(self):
        activity_id = save_activity(self.database_path, self.activity)
        before = dict(get_activity(self.database_path, activity_id))
        journal = self.client.get("/journal")
        self.assertIn(f'href="/activities/{activity_id}/delete"'.encode(), journal.data)
        for _ in range(2):
            response = self.client.get(f"/activities/{activity_id}/delete")
            self.assertEqual(response.status_code, 200)
            for value in self.activity.values():
                self.assertIn(value.encode(), response.data)
            self.assertIn(b"Cancel and keep activity", response.data)
        # Cancel is a link to the journal, with no form submission.
        self.client.get("/journal")
        self.assertEqual(dict(get_activity(self.database_path, activity_id)), before)

    def test_confirmed_delete_removes_only_selected_activity(self):
        activity_id = save_activity(self.database_path, self.activity)
        other_id = save_activity(self.database_path, {**self.activity, "title": "Keep this one"})
        other_before = dict(get_activity(self.database_path, other_id))
        token = self.get_delete_token(activity_id)
        response = self.client.post(
            f"/activities/{activity_id}/delete",
            data={"confirmation_token": token, "id": other_id},
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith("/journal"))
        self.assertIsNone(get_activity(self.database_path, activity_id))
        self.assertEqual(dict(get_activity(self.database_path, other_id)), other_before)
        fresh_client = app.test_client()
        for _ in range(2):
            journal = fresh_client.get(response.location)
            self.assertEqual(journal.status_code, 200)
            self.assertNotIn(b"Practised squats", journal.data)
            self.assertIn(b"Keep this one", journal.data)
        self.assertEqual(self.client.get(f"/activities/{activity_id}/saved").status_code, 404)
        self.assertEqual(self.client.get(f"/activities/{activity_id}/edit").status_code, 404)

    def test_delete_requires_valid_confirmation_for_same_browser_and_activity(self):
        activity_id = save_activity(self.database_path, self.activity)
        other_id = save_activity(self.database_path, {**self.activity, "title": "Keep this one"})
        before = [dict(row) for row in list_activities(self.database_path)]
        url = f"/activities/{activity_id}/delete"
        self.assertEqual(self.client.post(url).status_code, 400)
        token = self.get_delete_token(activity_id)
        for invalid_token in ("", "wrong-token", "\u2603"):
            with self.subTest(token=invalid_token):
                response = self.client.post(url, data={"confirmation_token": invalid_token})
                self.assertEqual(response.status_code, 400)
        response = app.test_client().post(url, data={"confirmation_token": token})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            f"/activities/{other_id}/delete", data={"confirmation_token": token}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual([dict(row) for row in list_activities(self.database_path)], before)

    def test_delete_last_activity_shows_empty_journal_and_consumes_token(self):
        activity_id = save_activity(self.database_path, self.activity)
        token = self.get_delete_token(activity_id)
        response = self.client.post(
            f"/activities/{activity_id}/delete",
            data={"confirmation_token": token}, follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No activities recorded yet", response.data)
        self.assertEqual(list_activities(self.database_path), [])
        # SQLite may reuse a deleted ID. The old confirmation must not delete a new row.
        new_id = save_activity(self.database_path, self.activity)
        response = self.client.post(
            f"/activities/{new_id}/delete", data={"confirmation_token": token}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(get_activity(self.database_path, new_id))

    def test_delete_missing_activity_returns_404(self):
        self.assertEqual(self.client.get("/activities/999/delete").status_code, 404)
        self.assertEqual(self.client.post("/activities/999/delete").status_code, 404)
        self.assertEqual(list_activities(self.database_path), [])


if __name__ == "__main__":
    unittest.main()
