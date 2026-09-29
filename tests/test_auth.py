"""Account and form-protection checks, using a separate temporary database."""

import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from jinja2 import ChoiceLoader, DictLoader
from werkzeug.security import check_password_hash

from auth import get_user_id, init_app
from database import connect_database as connect_app_database, get_activity


class AuthTests(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.database_path = Path(temporary_directory.name) / "auth.sqlite3"
        # Keep these focused tests independent of the main app's other features.
        with closing(self.connect_database(self.database_path)) as connection:
            connection.executescript("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE activities (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    user_id INTEGER REFERENCES users(id)
                );
            """)
        database_patch = patch("auth.connect_database", self.connect_database)
        database_patch.start()
        self.addCleanup(database_patch.stop)
        template_path = Path(__file__).resolve().parent.parent / "templates"
        self.app = Flask(__name__, template_folder=str(template_path))
        self.app.config.update(
            TESTING=True, DATABASE=self.database_path, SECRET_KEY="test-key-only",
        )
        # Auth pages still render their real templates, within a minimal test layout.
        self.app.jinja_loader = ChoiceLoader([
            DictLoader({"base.html": "{% block title %}{% endblock %}{% block content %}{% endblock %}"}),
            self.app.jinja_loader,
        ])
        init_app(self.app)
        self.app.add_url_rule("/", "home", lambda: f"Account {get_user_id()}")
        self.mutations = []

        def protected_change():
            self.mutations.append(get_user_id())
            return "Saved"

        self.app.add_url_rule("/change", "change", protected_change, methods=["POST"])
        self.client = self.app.test_client()
        self.credentials = {
            "username": "learner",
            "password": "growth each morning",
            "password_confirmation": "growth each morning",
        }

    @staticmethod
    def connect_database(database_path):
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def token(self, path, client=None):
        response = (client or self.client).get(path)
        self.assertEqual(response.status_code, 200)
        return re.search(
            r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True)
        ).group(1)

    def setup_account(self):
        response = self.client.post("/setup", data={
            **self.credentials, "csrf_token": self.token("/setup"),
        })
        self.assertEqual(response.status_code, 303)
        return response

    def logout(self):
        response = self.client.post("/logout", data={"csrf_token": self.token("/account")})
        self.assertEqual(response.status_code, 303)

    def test_anonymous_requests_go_to_setup_then_login(self):
        self.assertTrue(self.client.get("/").location.endswith("/setup"))
        self.assertTrue(self.client.get("/login").location.endswith("/setup"))
        self.assertTrue(self.client.get("/register").location.endswith("/setup"))
        self.setup_account()
        self.logout()
        self.assertTrue(self.client.get("/").location.endswith("/login"))
        self.assertTrue(self.client.get("/setup").location.endswith("/login"))
        self.assertTrue(self.client.post("/change").location.endswith("/login"))
        self.assertEqual(self.mutations, [])

    def test_first_account_claims_existing_activities_and_hashes_password(self):
        with closing(self.connect_database(self.database_path)) as connection:
            connection.execute("INSERT INTO activities (title) VALUES ('An existing reflection')")
            connection.commit()
        with self.client.session_transaction() as session:
            session["old_confirmation"] = "must be cleared"
        self.setup_account()
        with closing(self.connect_database(self.database_path)) as connection:
            user = connection.execute("SELECT * FROM users").fetchone()
            activity = connection.execute("SELECT * FROM activities").fetchone()
        self.assertEqual(activity["user_id"], user["id"])
        self.assertNotEqual(user["password_hash"], self.credentials["password"])
        self.assertTrue(check_password_hash(user["password_hash"], self.credentials["password"]))
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], user["id"])
            self.assertNotIn("old_confirmation", session)
        self.assertIn(f"Account {user['id']}".encode(), self.client.get("/").data)

    def test_registration_never_takes_another_users_or_unowned_records(self):
        self.setup_account()
        with closing(self.connect_database(self.database_path)) as connection:
            connection.execute("INSERT INTO activities (title, user_id) VALUES ('Original', 1)")
            connection.execute("INSERT INTO activities (title) VALUES ('Unowned')")
            connection.commit()
        self.logout()
        response = self.client.post("/register", data={
            **self.credentials, "username": "another", "csrf_token": self.token("/register"),
        })
        self.assertEqual(response.status_code, 303)
        with closing(self.connect_database(self.database_path)) as connection:
            owners = [row[0] for row in connection.execute("SELECT user_id FROM activities ORDER BY id")]
            self.assertEqual(connection.execute("SELECT count(*) FROM users").fetchone()[0], 2)
        self.assertEqual(owners, [1, None])
        self.assertIn(b"Account 2", self.client.get("/").data)
        # A later visit or POST to setup cannot claim the unowned record.
        response = self.client.post("/setup", data={"csrf_token": self.token("/account")})
        self.assertEqual(response.status_code, 303)
        with closing(self.connect_database(self.database_path)) as connection:
            self.assertIsNone(connection.execute("SELECT user_id FROM activities WHERE title = 'Unowned'").fetchone()[0])

    def test_invalid_signup_and_duplicate_username_do_not_create_accounts(self):
        token = self.token("/setup")
        for changes in (
            {"username": ""}, {"username": "has spaces"}, {"username": "x" * 41},
            {"password": "short"}, {"password_confirmation": "different"},
            {"password": "x" * 257, "password_confirmation": "x" * 257},
        ):
            with self.subTest(changes=changes):
                response = self.client.post("/setup", data={
                    **self.credentials, **changes, "csrf_token": token,
                })
                self.assertEqual(response.status_code, 400)
                self.assertNotIn(self.credentials["password"].encode(), response.data)
        with closing(self.connect_database(self.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM users").fetchone()[0], 0)
        self.setup_account()
        self.logout()
        response = self.client.post("/register", data={
            **self.credentials, "username": "LEARNER", "csrf_token": self.token("/register"),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"already in use", response.data)
        with closing(self.connect_database(self.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM users").fetchone()[0], 1)

    def test_csrf_protects_public_forms_and_is_bound_to_browser(self):
        token = self.token("/setup")
        for submitted in ("", "wrong-token", "\u2603"):
            with self.subTest(token=submitted):
                response = self.client.post("/setup", data={**self.credentials, "csrf_token": submitted})
                self.assertEqual(response.status_code, 400)
        other_browser = self.app.test_client()
        response = other_browser.post("/setup", data={**self.credentials, "csrf_token": token})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(self.client.get("/").location.endswith("/setup"))
        response = self.client.post("/setup", data=self.credentials, headers={"X-CSRFToken": token})
        self.assertEqual(response.status_code, 303)

    def test_csrf_protects_modifying_routes_and_logout(self):
        self.setup_account()
        token = self.token("/account")
        self.assertEqual(self.client.post("/change").status_code, 400)
        self.assertEqual(self.client.post("/logout").status_code, 400)
        self.assertEqual(self.mutations, [])
        self.assertEqual(self.client.get("/logout").status_code, 405)
        self.assertEqual(self.client.post("/change", headers={"X-CSRFToken": token}).status_code, 200)
        self.assertEqual(self.mutations, [1])
        self.logout()
        response = self.client.post("/login", data={
            **self.credentials, "csrf_token": token,
        })
        self.assertEqual(response.status_code, 400)

    def test_login_uses_case_insensitive_username_and_generic_errors(self):
        self.setup_account()
        self.logout()
        token = self.token("/login")
        for username, password in (("learner", "wrong"), ("missing", "wrong")):
            response = self.client.post("/login", data={
                "username": username, "password": password, "csrf_token": token,
            })
            self.assertEqual(response.status_code, 400)
            self.assertIn(b"The username or password is incorrect.", response.data)
        response = self.client.post("/login?next=https://example.com", data={
            **self.credentials, "username": "LEARNER", "csrf_token": token,
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.location, "/")

    def test_change_password_requires_current_password_and_updates_login(self):
        self.setup_account()
        new_password = "a fresh growth password"
        form = {
            "current_password": "incorrect",
            "password": new_password, "password_confirmation": new_password,
            "csrf_token": self.token("/account"),
        }
        response = self.client.post("/account", data=form)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Your current password is incorrect.", response.data)
        form["current_password"] = self.credentials["password"]
        response = self.client.post("/account", data=form)
        self.assertEqual(response.status_code, 303)
        self.assertIn(b"Your password has been changed.", self.client.get(response.location).data)
        self.logout()
        token = self.token("/login")
        self.assertEqual(self.client.post("/login", data={**self.credentials, "csrf_token": token}).status_code, 400)
        self.assertEqual(self.client.post("/login", data={
            **self.credentials, "password": new_password, "csrf_token": token,
        }).status_code, 303)

    def test_login_bypass_requires_explicit_testing_flag(self):
        self.app.config.update(LOGIN_DISABLED=True, TESTING=False)
        self.assertTrue(self.client.get("/").location.endswith("/setup"))
        self.app.config["TESTING"] = True
        self.assertIn(b"Account None", self.client.get("/").data)

    def test_real_migration_and_setup_preserve_and_claim_legacy_activity(self):
        # Exercise the real schema upgrade on a disposable milestone-1 database.
        legacy_path = self.database_path.with_name("legacy.sqlite3")
        with closing(sqlite3.connect(legacy_path)) as connection:
            connection.execute("""
                CREATE TABLE activities (
                    id INTEGER PRIMARY KEY,
                    activity_date TEXT NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    what_i_did TEXT NOT NULL,
                    reflection TEXT NOT NULL
                )
            """)
            connection.execute("""
                INSERT INTO activities VALUES (
                    7, '2026-09-28', 'Original journal entry', 'Reading', 20,
                    'Read a chapter', 'Learned about consistency'
                )
            """)
            connection.commit()
        self.app.config["DATABASE"] = legacy_path
        with patch("auth.connect_database", connect_app_database):
            self.setup_account()
            activity = get_activity(legacy_path, 7, user_id=1)
            self.assertEqual(activity["reflection"], "Learned about consistency")
            self.assertIsNone(get_activity(legacy_path, 7, user_id=None))
            self.logout()
            response = self.client.post("/register", data={
                **self.credentials, "username": "second", "csrf_token": self.token("/register"),
            })
            self.assertEqual(response.status_code, 303)
            self.assertIsNone(get_activity(legacy_path, 7, user_id=2))
        backups = list((legacy_path.parent / "backups").glob("*.sqlite3"))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as connection:
            self.assertEqual(connection.execute("SELECT title FROM activities WHERE id = 7").fetchone()[0], "Original journal entry")


if __name__ == "__main__":
    unittest.main()
