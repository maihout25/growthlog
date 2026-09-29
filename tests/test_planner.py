"""Behavior checks for intentions, recurrence, and local reminders."""

import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from app import app, LOCAL_TIMEZONE
from database import connect_database, delete_activity, get_growth_dates


class PlannerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database_path = Path(directory.name) / "planner.sqlite3"
        settings = patch.dict(app.config, DATABASE=self.database_path, TESTING=True,
                              LOGIN_DISABLED=False, CSRF_ENABLED=False)
        settings.start()
        self.addCleanup(settings.stop)
        clock = patch("app.local_today", return_value=date(2026, 9, 29))
        clock.start()
        self.addCleanup(clock.stop)
        reminder_clock = patch("planner.local_now", return_value=datetime(2026, 9, 29, 10, 0, tzinfo=LOCAL_TIMEZONE))
        reminder_clock.start()
        self.addCleanup(reminder_clock.stop)
        with closing(connect_database(self.database_path)) as connection:
            connection.executemany("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                                   [("learner", "unused-test-hash"), ("other", "unused-test-hash")])
            connection.commit()
        self.client = app.test_client()
        self.sign_in(1)
        self.task = {"title": "Read a chapter", "category": "Reading", "notes": "Practice carefully",
                     "planned_date": "2026-09-29", "planned_time": "10:00", "reminder_minutes": "15"}
        self.habit = {"title": "Morning walk", "category": "Fitness", "notes": "",
                      "weekdays": ["1", "3"], "start_date": "2026-09-28", "end_date": "2026-10-02",
                      "planned_time": "10:00", "reminder_minutes": "0"}
        self.activity = {"activity_date": "2026-09-29", "title": "Read a chapter", "category": "Reading",
                         "duration_minutes": "20", "what_i_did": "Read and took notes.",
                         "reflection": "Learned how loops repeat an action."}

    def sign_in(self, user_id):
        with self.client.session_transaction() as session:
            session["user_id"] = user_id

    def rows(self, table):
        with closing(connect_database(self.database_path)) as connection:
            return connection.execute(f"SELECT * FROM {table}").fetchall()

    def create_task(self, **changes):
        response = self.client.post("/tasks/new", data={**self.task, **changes})
        self.assertEqual(response.status_code, 303)
        return self.rows("planned_tasks")[-1]["id"]

    def create_habit(self, **changes):
        response = self.client.post("/habits/new", data={**self.habit, **changes})
        self.assertEqual(response.status_code, 303)
        return self.rows("habits")[-1]["id"]

    def test_plans_stay_separate_from_completed_growth(self):
        self.create_task(planned_date="2026-10-10")
        self.create_task(planned_date="", planned_time="", reminder_minutes="")
        self.create_habit()
        self.assertEqual(self.rows("activities"), [])
        self.assertEqual(get_growth_dates(self.database_path, date(2026, 9, 28), date(2026, 10, 4), 1), set())
        response = self.client.get("/planner")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Unscheduled", response.data)
        self.assertIn(b"Tuesday, Thursday", response.data)

    def test_task_edit_and_delete_confirmation_preserve_activity(self):
        task_id = self.create_task()
        response = self.client.post(f"/tasks/{task_id}/edit", data={**self.task, "title": "Read two chapters"})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.rows("planned_tasks")[0]["title"], "Read two chapters")
        self.client.post(f"/tasks/{task_id}/complete", data=self.activity)
        self.assertEqual(self.client.get(f"/tasks/{task_id}/delete").status_code, 200)
        self.assertEqual(len(self.rows("planned_tasks")), 1)
        self.assertEqual(self.client.post(f"/tasks/{task_id}/delete").status_code, 400)
        self.assertEqual(self.client.post(f"/tasks/{task_id}/delete", data={"confirm": "delete"}).status_code, 303)
        self.assertEqual(self.rows("planned_tasks"), [])
        self.assertEqual(len(self.rows("activities")), 1)

    def test_plan_validation_does_not_save_bad_dates_or_reminders(self):
        for change in ({"title": " "}, {"category": "Unknown"}, {"planned_date": "2026-02-30"},
                       {"planned_time": "25:00"}, {"planned_time": "10:00+03:00"},
                       {"reminder_minutes": "-1"}, {"planned_date": ""}, {"planned_time": ""}):
            with self.subTest(change=change):
                self.assertEqual(self.client.post("/tasks/new", data={**self.task, **change}).status_code, 400)
        self.assertEqual(self.rows("planned_tasks"), [])

    def test_edit_form_selects_saved_reminder(self):
        task_id = self.create_task(reminder_minutes="0")
        response = self.client.get(f"/tasks/{task_id}/edit")
        self.assertIn(b'value="0" selected', response.data)

    def test_completion_requires_valid_actual_date_and_reflection(self):
        task_id = self.create_task(planned_date="2026-10-10")
        for change in ({"reflection": " "}, {"activity_date": "2026-09-30"}, {"duration_minutes": "0"}):
            with self.subTest(change=change):
                response = self.client.post(f"/tasks/{task_id}/complete", data={**self.activity, **change})
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.rows("activities"), [])
        self.assertIsNone(self.rows("planned_tasks")[0]["activity_id"])
        # An intention scheduled for the future can be completed early, using today's actual date.
        self.assertEqual(self.client.post(f"/tasks/{task_id}/complete", data=self.activity).status_code, 303)
        self.assertEqual(get_growth_dates(self.database_path, date(2026, 9, 28), date(2026, 9, 29), 1), {"2026-09-29"})

    def test_task_completion_is_idempotent_and_activity_deletion_reopens_plan(self):
        task_id = self.create_task()
        first = self.client.post(f"/tasks/{task_id}/complete", data=self.activity)
        second = self.client.post(f"/tasks/{task_id}/complete", data=self.activity)
        self.assertEqual(first.location, second.location)
        self.assertEqual(len(self.rows("activities")), 1)
        activity_id = self.rows("activities")[0]["id"]
        delete_activity(self.database_path, activity_id, 1)
        self.assertIsNone(self.rows("planned_tasks")[0]["activity_id"])
        self.assertEqual(self.client.get(f"/tasks/{task_id}/complete").status_code, 200)

    def test_habit_recurrence_week_boundaries_and_validation(self):
        for change in ({"weekdays": []}, {"weekdays": ["7"]}, {"start_date": ""},
                       {"end_date": "2026-09-01"}, {"start_date": "no date"}):
            with self.subTest(change=change):
                self.assertEqual(self.client.post("/habits/new", data={**self.habit, **change}).status_code, 400)
        habit_id = self.create_habit()
        current = self.client.get("/schedule?week=2026-09-30")
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.data.count(b"Morning walk"), 2)
        self.assertIn(f"/habits/{habit_id}/complete/2026-09-29".encode(), current.data)
        self.assertNotIn(f"/habits/{habit_id}/complete/2026-10-01".encode(), current.data)
        self.assertNotIn(b"Morning walk", self.client.get("/schedule?week=2026-10-05").data)
        self.assertNotIn(b"Morning walk", self.client.get("/schedule?week=2026-09-21").data)
        self.assertEqual(self.client.get("/schedule?week=0001-01-01").status_code, 400)
        self.assertEqual(self.client.get("/schedule?week=nonsense").status_code, 400)

    def test_habit_completion_validates_occurrence_and_is_idempotent(self):
        habit_id = self.create_habit()
        for occurrence in ("2026-09-28", "2026-09-22", "2026-10-01", "invalid"):
            with self.subTest(occurrence=occurrence):
                self.assertIn(self.client.post(f"/habits/{habit_id}/complete/{occurrence}", data=self.activity).status_code, (400, 404))
        self.assertEqual(self.rows("activities"), [])
        url = f"/habits/{habit_id}/complete/2026-09-29"
        first = self.client.post(url, data=self.activity)
        second = self.client.post(url, data=self.activity)
        self.assertEqual(first.status_code, 303)
        self.assertEqual(first.location, second.location)
        self.assertEqual(len(self.rows("activities")), 1)
        self.assertEqual(len(self.rows("habit_completions")), 1)
        self.assertEqual(self.client.get(url).location, first.location)

    def test_schedule_keeps_historical_completion_after_habit_edit_and_archive(self):
        habit_id = self.create_habit()
        self.client.post(f"/habits/{habit_id}/complete/2026-09-29", data={**self.activity, "activity_date": "2026-09-28"})
        self.assertEqual(self.client.post(f"/habits/{habit_id}/edit", data={**self.habit, "weekdays": ["0"]}).status_code, 303)
        self.assertEqual(self.client.post(f"/habits/{habit_id}/archive").status_code, 303)
        self.assertEqual(self.rows("habits")[0]["active"], 0)
        schedule = self.client.get("/schedule?week=2026-09-28")
        self.assertEqual(schedule.data.count(b"Morning walk"), 1)
        self.assertIn(b"Activity date: 2026-09-28", schedule.data)
        self.assertEqual(get_growth_dates(self.database_path, date(2026, 9, 28), date(2026, 9, 29), 1), {"2026-09-28"})
        self.client.post(f"/habits/{habit_id}/archive")
        self.assertEqual(self.rows("habits")[0]["active"], 1)

    def test_deleting_activity_removes_habit_completion(self):
        habit_id = self.create_habit()
        self.client.post(f"/habits/{habit_id}/complete/2026-09-29", data=self.activity)
        delete_activity(self.database_path, self.rows("activities")[0]["id"], 1)
        self.assertEqual(self.rows("habit_completions"), [])
        schedule = self.client.get("/schedule")
        self.assertIn(f"/habits/{habit_id}/complete/2026-09-29".encode(), schedule.data)

    def test_ownership_is_enforced_for_pages_updates_and_completions(self):
        task_id = self.create_task()
        habit_id = self.create_habit()
        self.sign_in(2)
        for url in (f"/tasks/{task_id}/edit", f"/tasks/{task_id}/delete", f"/tasks/{task_id}/complete",
                    f"/habits/{habit_id}/edit", f"/habits/{habit_id}/complete/2026-09-29"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(self.client.post(url, data=self.activity).status_code, 404)
        self.assertEqual(self.client.post(f"/habits/{habit_id}/archive").status_code, 404)
        self.assertNotIn(b"Read a chapter", self.client.get("/planner").data)
        self.assertNotIn(b"Morning walk", self.client.get("/schedule").data)
        self.assertEqual(self.client.get("/api/reminders").json, {"reminders": []})
        self.assertEqual(self.rows("activities"), [])

    def test_due_reminders_dismiss_persist_and_exclude_other_times(self):
        self.create_task()
        self.create_habit()
        self.create_task(title="Tomorrow", planned_date="2026-09-30", reminder_minutes="1440")
        self.create_task(title="Later today", planned_time="11:00", reminder_minutes="0")
        self.create_task(title="Yesterday", planned_date="2026-09-28")
        response = self.client.get("/api/reminders")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual({item["title"] for item in response.json["reminders"]}, {"Read a chapter", "Morning walk", "Tomorrow"})
        reminder = response.json["reminders"][0]
        self.assertEqual(self.client.post("/api/reminders/dismiss", json={"reminder_key": reminder["reminder_key"]}).status_code, 200)
        self.assertNotIn(reminder["reminder_key"], {row["reminder_key"] for row in self.client.get("/api/reminders").json["reminders"]})
        self.assertEqual(len(self.rows("reminder_dismissals")), 1)
        self.assertEqual(self.client.post("/api/reminders/dismiss", json={"reminder_key": "invented"}).status_code, 400)
        self.assertEqual(self.client.post("/api/reminders/dismiss", json=["wrong shape"]).status_code, 400)

    def test_completing_or_archiving_stops_reminders(self):
        task_id = self.create_task()
        habit_id = self.create_habit()
        self.assertEqual(len(self.client.get("/api/reminders").json["reminders"]), 2)
        self.client.post(f"/tasks/{task_id}/complete", data=self.activity)
        self.client.post(f"/habits/{habit_id}/archive")
        self.assertEqual(self.client.get("/api/reminders").json, {"reminders": []})

    def test_csrf_protects_task_creation_and_reminder_dismissal(self):
        with patch.dict(app.config, CSRF_ENABLED=True):
            self.client.get("/planner")
            self.assertEqual(self.client.post("/tasks/new", data=self.task).status_code, 400)
            with self.client.session_transaction() as session:
                token = session["csrf_token"]
            self.assertEqual(self.client.post("/tasks/new", data={**self.task, "csrf_token": token}).status_code, 303)
            key = self.client.get("/api/reminders").json["reminders"][0]["reminder_key"]
            self.assertEqual(self.client.post("/api/reminders/dismiss", json={"reminder_key": key}).status_code, 400)
            response = self.client.post("/api/reminders/dismiss", json={"reminder_key": key}, headers={"X-CSRFToken": token})
            self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
