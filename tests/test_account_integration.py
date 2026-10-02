"""Run the real routes with accounts, ownership checks, and CSRF enabled."""

import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

# Importing the test app must not create or read a real local session key.
with patch("configuration.load_secret_key", return_value="integration-test-key"):
    from app import app

from database import get_activity, list_activities


class AccountIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database_path = Path(directory.name) / "accounts.sqlite3"
        settings = patch.dict(
            app.config, DATABASE=self.database_path, TESTING=True,
            LOGIN_DISABLED=False, CSRF_ENABLED=True,
        )
        settings.start()
        self.addCleanup(settings.stop)
        clock = patch("app.local_today", return_value=date(2026, 9, 29))
        clock.start()
        self.addCleanup(clock.stop)
        self.first = app.test_client()
        self.second = app.test_client()
        self.register(self.first, "/setup", "first")
        self.register(self.second, "/register", "second")
        self.activity = {
            "activity_date": "2026-09-28", "title": "Private first activity", "category": "Fitness",
            "duration_minutes": "20", "what_i_did": "Practised balance.",
            "reflection": "A private first reflection.",
        }

    def get_form(self, client, url):
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def csrf(self, client, url):
        return re.search(
            r'name="csrf_token" value="([^"]+)"', self.get_form(client, url)
        ).group(1)

    def register(self, client, path, username):
        response = client.post(path, data={
            "username": username, "password": "practice learning daily",
            "password_confirmation": "practice learning daily",
            "csrf_token": self.csrf(client, path),
        })
        self.assertEqual(response.status_code, 303)

    def save_first_activity(self):
        response = self.first.post("/activities/new", data={
            **self.activity, "csrf_token": self.csrf(self.first, "/activities/new"),
            "user_id": "2",
        })
        self.assertEqual(response.status_code, 303)
        return int(re.search(r"/activities/(\d+)/saved", response.location).group(1))

    def test_accounts_cannot_view_modify_delete_or_count_each_others_activities(self):
        activity_id = self.save_first_activity()
        self.assertEqual(get_activity(self.database_path, activity_id, 1)["user_id"], 1)
        self.assertIsNone(get_activity(self.database_path, activity_id, 2))
        self.assertIn(self.activity["reflection"].encode(), self.first.get("/journal").data)
        self.assertNotIn(self.activity["reflection"].encode(), self.second.get("/journal").data)
        self.assertIn(b"1 growth day this week", self.first.get("/").data)
        self.assertIn(b"0 growth days this week", self.second.get("/").data)

        for suffix in ("saved", "edit", "delete", "fitness"):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.second.get(f"/activities/{activity_id}/{suffix}").status_code, 404)
        second_csrf = self.csrf(self.second, "/activities/new")
        response = self.second.post(f"/activities/{activity_id}/edit", data={
            **self.activity, "title": "Forbidden edit", "csrf_token": second_csrf,
        })
        self.assertEqual(response.status_code, 404)

        # Even copying another browser's delete confirmation cannot cross ownership.
        first_confirmation = re.search(
            r'name="confirmation_token" value="([^"]+)"',
            self.get_form(self.first, f"/activities/{activity_id}/delete"),
        ).group(1)
        response = self.second.post(f"/activities/{activity_id}/delete", data={
            "confirmation_token": first_confirmation, "csrf_token": second_csrf,
        })
        self.assertEqual(response.status_code, 404)
        self.assertEqual(get_activity(self.database_path, activity_id, 1)["title"], self.activity["title"])

        response = self.second.post("/activities/new", data={
            **self.activity, "activity_date": "2026-09-29", "title": "Second account's activity",
            "user_id": "1", "csrf_token": second_csrf,
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(len(list_activities(self.database_path, 1)), 1)
        self.assertEqual(len(list_activities(self.database_path, 2)), 1)
        self.assertNotIn(b"Second account&#39;s activity", self.first.get("/journal").data)
        self.assertIn(b"1 growth day this week", self.second.get("/").data)

    def test_core_create_edit_delete_reject_missing_csrf_without_mutations(self):
        response = self.first.post("/activities/new", data=self.activity)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(list_activities(self.database_path, 1), [])
        activity_id = self.save_first_activity()
        before = dict(get_activity(self.database_path, activity_id, 1))
        response = self.first.post(f"/activities/{activity_id}/edit", data={
            **self.activity, "title": "Unsaved edit",
        })
        self.assertEqual(response.status_code, 400)
        confirmation = re.search(
            r'name="confirmation_token" value="([^"]+)"',
            self.get_form(self.first, f"/activities/{activity_id}/delete"),
        ).group(1)
        response = self.first.post(f"/activities/{activity_id}/delete", data={
            "confirmation_token": confirmation,
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(dict(get_activity(self.database_path, activity_id, 1)), before)
        response = self.first.post(f"/activities/{activity_id}/delete", data={
            "confirmation_token": confirmation,
            "csrf_token": self.csrf(self.first, "/activities/new"),
        })
        self.assertEqual(response.status_code, 303)
        self.assertIsNone(get_activity(self.database_path, activity_id, 1))
        self.assertIn(b"0 growth days this week", self.first.get("/").data)

    def test_hosted_signup_starts_with_private_empty_journal(self):
        activity_id = self.save_first_activity()
        with patch.dict(app.config, PRODUCTION=True, ALLOW_SETUP=False):
            visitor = app.test_client()
            self.assertIn('href="/register"', self.get_form(visitor, "/login"))
            self.assertIn("Sign up", self.get_form(visitor, "/register"))
            self.register(visitor, "/register", "new_reader")
            self.assertIn(b"0 growth days this week", visitor.get("/").data)
            self.assertIn(b"No activities recorded yet", visitor.get("/journal").data)
            self.assertNotIn(self.activity["reflection"].encode(), visitor.get("/journal").data)
            self.assertEqual(visitor.get(f"/activities/{activity_id}/edit").status_code, 404)
            self.assertEqual(visitor.get("/setup").status_code, 403)
            self.assertIn(self.activity["reflection"].encode(), self.first.get("/journal").data)

    def test_logout_protects_pages_and_requires_fresh_login(self):
        activity_id = self.save_first_activity()
        response = self.first.post("/logout", data={"csrf_token": self.csrf(self.first, "/account")})
        self.assertEqual(response.status_code, 303)
        for url in ("/", "/journal", f"/activities/{activity_id}/saved", "/planner", "/schedule", "/api/reminders"):
            with self.subTest(url=url):
                response = self.first.get(url)
                self.assertEqual(response.status_code, 303)
                self.assertTrue(response.location.endswith("/login"))
                self.assertNotIn(self.activity["reflection"].encode(), response.data)
        response = self.first.post("/login", data={
            "username": "first", "password": "practice learning daily",
            "csrf_token": self.csrf(self.first, "/login"),
        })
        self.assertEqual(response.status_code, 303)
        self.assertIn(self.activity["reflection"].encode(), self.first.get("/journal").data)


if __name__ == "__main__":
    unittest.main()
