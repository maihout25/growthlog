"""Check the hosting boundary with temporary data, never the personal journal."""

import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from jinja2 import ChoiceLoader, DictLoader
from werkzeug.security import check_password_hash

from administration import init_commands
from auth import init_app
from configuration import configure_hosting
from database import connect_database
from login_throttle import LoginThrottle


class HostingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data_path = Path(self.directory.name)
        self.environment = patch.dict(os.environ, {
            "GROWTHLOG_ENV": "production",
            "GROWTHLOG_TRUSTED_HOSTS": "growthlog.example",
            "GROWTHLOG_DATA_DIR": str(self.data_path),
            "GROWTHLOG_SECRET_KEY": "",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        template_path = Path(__file__).resolve().parent.parent / "templates"
        self.app = Flask(__name__, template_folder=str(template_path))
        configure_hosting(self.app)
        self.app.testing = True
        self.app.jinja_loader = ChoiceLoader([
            DictLoader({"base.html": "{% block content %}{% endblock %}"}),
            self.app.jinja_loader,
        ])
        init_app(self.app)
        init_commands(self.app)
        self.app.add_url_rule("/", "home", lambda: "Private dashboard")
        self.client = self.app.test_client()
        self.runner = self.app.test_cli_runner()

    def get(self, path):
        return self.client.get(path, base_url="https://growthlog.example")

    def token(self):
        return re.search(
            r'name="csrf_token" value="([^"]+)"', self.get("/login").get_data(as_text=True)
        ).group(1)

    def create_user(self, username="learner"):
        result = self.runner.invoke(args=["create-user"], input=f"{username}\ngrow a little daily\ngrow a little daily\n")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn("grow a little daily", result.output)
        return result

    def test_production_requires_an_explicit_hostname(self):
        with patch.dict(os.environ, {"GROWTHLOG_TRUSTED_HOSTS": ""}):
            with self.assertRaisesRegex(RuntimeError, "hostname"):
                configure_hosting(Flask("missing-host"))

    def test_secret_and_database_location_survive_a_new_app_instance(self):
        second_app = Flask("second-worker")
        configure_hosting(second_app)
        self.assertEqual(self.app.secret_key, second_app.secret_key)
        self.assertEqual(self.app.config["DATABASE"], self.data_path / "growthlog.sqlite3")
        self.assertFalse(second_app.debug)
        self.assertFalse(second_app.testing)

    def test_local_workflow_keeps_registration_and_http_cookies(self):
        with patch.dict(os.environ, {"GROWTHLOG_ENV": "local", "GROWTHLOG_TRUSTED_HOSTS": ""}):
            local_app = Flask("local")
            configure_hosting(local_app)
        self.assertTrue(local_app.config["ALLOW_REGISTRATION"])
        self.assertFalse(local_app.config["SESSION_COOKIE_SECURE"])
        self.assertIsNone(local_app.config["TRUSTED_HOSTS"])

    def test_empty_hosted_app_does_not_offer_first_account_to_a_visitor(self):
        self.assertTrue(self.get("/").location.endswith("/login"))
        response = self.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('href="/register"', response.get_data(as_text=True))
        self.assertEqual(self.get("/setup").status_code, 403)
        self.assertEqual(self.get("/register").status_code, 403)
        response = self.client.post("/setup", base_url="https://growthlog.example", data={
            "csrf_token": self.token(), "username": "visitor",
            "password": "grow a little daily", "password_confirmation": "grow a little daily",
        })
        self.assertEqual(response.status_code, 403)
        with closing(connect_database(self.app.config["DATABASE"])) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM users").fetchone()[0], 0)

    def test_cli_account_is_hashed_and_can_sign_in_over_https(self):
        self.create_user()
        with closing(connect_database(self.app.config["DATABASE"])) as connection:
            user = connection.execute("SELECT * FROM users").fetchone()
            self.assertTrue(check_password_hash(user["password_hash"], "grow a little daily"))
        response = self.client.post("/login", base_url="https://growthlog.example", data={
            "csrf_token": self.token(), "username": "LEARNER", "password": "grow a little daily",
        })
        self.assertEqual(response.status_code, 303)
        cookie = response.headers["Set-Cookie"]
        for attribute in ("Secure", "HttpOnly", "SameSite=Lax"):
            self.assertIn(attribute, cookie)
        self.assertEqual(self.get("/").data, b"Private dashboard")
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_untrusted_host_is_rejected_before_authentication_redirect(self):
        response = self.client.get("/", base_url="https://attacker.example")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Location", response.headers)

    def test_cli_rejects_duplicate_and_weak_accounts_without_changes(self):
        self.create_user()
        duplicate = self.runner.invoke(args=["create-user"], input="LEARNER\nother strong password\nother strong password\n")
        weak = self.runner.invoke(args=["create-user"], input="another\nshort\nshort\n")
        self.assertNotEqual(duplicate.exit_code, 0)
        self.assertNotEqual(weak.exit_code, 0)
        with closing(connect_database(self.app.config["DATABASE"])) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM users").fetchone()[0], 1)

    def test_cli_first_account_claims_only_unowned_legacy_activities(self):
        with closing(connect_database(self.app.config["DATABASE"])) as connection:
            connection.execute("""INSERT INTO activities
                (activity_date, title, category, duration_minutes, what_i_did, reflection)
                VALUES ('2026-09-28', 'Read', 'Reading', 10, 'Read a chapter', 'A useful idea')""")
            connection.commit()
        self.create_user()
        self.create_user("second")
        with closing(connect_database(self.app.config["DATABASE"])) as connection:
            self.assertEqual(connection.execute("SELECT user_id FROM activities").fetchone()[0], 1)

    def test_backup_is_a_separate_readable_snapshot(self):
        missing = self.runner.invoke(args=["backup-db"])
        self.assertNotEqual(missing.exit_code, 0)
        self.create_user()
        result = self.runner.invoke(args=["backup-db"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.create_user("later")
        backup = next((self.data_path / "backups").glob("*.sqlite3"))
        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(connection.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("SELECT username FROM users").fetchall(), [("learner",)])

    def test_hosted_login_throttles_repeated_attempts(self):
        self.create_user()
        data = {"csrf_token": self.token(), "username": "learner", "password": "incorrect"}
        for _ in range(8):
            response = self.client.post("/login", base_url="https://growthlog.example", data=data)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post("/login", base_url="https://growthlog.example", data=data).status_code, 429)

    def test_wsgi_entry_point_serves_real_app_without_the_development_server(self):
        # A fresh interpreter catches import-order mistakes in the deployment file.
        script = """
import runpy
import sys
from pathlib import Path
from unittest.mock import patch
home = Path(sys.argv[1])
with patch('pathlib.Path.home', return_value=home):
    application = runpy.run_path('deploy/pythonanywhere_wsgi.py')['application']
client = application.test_client()
base_url = f'https://{home.name}.pythonanywhere.com'
assert client.get('/login', base_url=base_url).status_code == 200
assert client.get('/setup', base_url=base_url).status_code == 403
assert not application.debug
assert application.config['DATABASE'] == home / 'growthlog' / 'instance' / 'growthlog.sqlite3'
assert client.get('/login', base_url='https://wrong.example').status_code == 400
print('Production WSGI entry point passed')
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(self.data_path)],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class LoginThrottleTests(unittest.TestCase):
    def test_names_are_case_insensitive_and_window_expires(self):
        throttle = LoginThrottle()
        with patch("login_throttle.monotonic", return_value=100):
            for _ in range(8):
                self.assertTrue(throttle.allow("Learner"))
            self.assertFalse(throttle.allow(" LEARNER "))
            self.assertTrue(throttle.allow("another"))
        with patch("login_throttle.monotonic", return_value=1000):
            self.assertTrue(throttle.allow("learner"))
            self.assertNotIn("another", throttle.by_username)

    def test_global_limit_covers_attempts_across_usernames(self):
        throttle = LoginThrottle()
        with patch("login_throttle.monotonic", return_value=100):
            for number in range(30):
                self.assertTrue(throttle.allow(str(number)))
            self.assertFalse(throttle.allow("next"))
            self.assertEqual(len(throttle.by_username), 30)
        with patch("login_throttle.monotonic", return_value=160):
            self.assertTrue(throttle.allow("next"))
