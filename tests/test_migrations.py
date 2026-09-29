"""Migration and linked-record checks never open the user's database."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from database import (
    connect_database, delete_activity, get_activity, get_growth_dates,
    list_activities, save_activity, update_activity,
)


LEGACY_SCHEMA = """
    CREATE TABLE activities (
        id INTEGER PRIMARY KEY,
        activity_date TEXT NOT NULL,
        title TEXT NOT NULL,
        category TEXT NOT NULL,
        duration_minutes INTEGER NOT NULL CHECK (duration_minutes BETWEEN 1 AND 1440),
        what_i_did TEXT NOT NULL,
        reflection TEXT NOT NULL CHECK (length(trim(reflection)) > 0)
    )
"""


class MigrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database_path = Path(directory.name) / "growthlog.sqlite3"
        self.activity = {
            "activity_date": "2026-09-28", "title": "Growth practice", "category": "Fitness",
            "duration_minutes": "20", "what_i_did": "Practised balance.",
            "reflection": "Improved stability.",
        }

    def add_users(self):
        with closing(connect_database(self.database_path)) as connection:
            connection.executemany(
                "INSERT INTO users (id, username, password_hash) VALUES (?, ?, 'test-only')",
                [(1, "first"), (2, "second")],
            )
            connection.commit()

    def test_legacy_migration_preserves_rows_and_original_backup_and_is_repeatable(self):
        originals = [
            (7, "2026-09-28", "Reader's notes", "Reading", 15, "Read a chapter.", "New perspective."),
            (11, "2026-09-29", "Balance practice", "Fitness", 20, "Practised squats.", "Better balance."),
        ]
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(LEGACY_SCHEMA)
            connection.executemany("INSERT INTO activities VALUES (?, ?, ?, ?, ?, ?, ?)", originals)
            connection.commit()

        for _ in range(3):
            with closing(connect_database(self.database_path)) as connection:
                rows = [tuple(row) for row in connection.execute("SELECT * FROM activities ORDER BY id")]
                self.assertEqual(rows, [(*row, None) for row in originals])
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

        backups = list((self.database_path.parent / "backups").glob("*.sqlite3"))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as connection:
            self.assertEqual(connection.execute("SELECT * FROM activities ORDER BY id").fetchall(), originals)
            self.assertNotIn("user_id", [row[1] for row in connection.execute("PRAGMA table_info(activities)")])
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_fresh_database_creates_all_tables_without_migration_backup(self):
        with closing(connect_database(self.database_path)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertTrue({
                "users", "activities", "planned_tasks", "habits", "habit_completions",
                "reminder_dismissals", "fitness_details", "weekly_reflections",
            }.issubset(tables))
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertFalse((self.database_path.parent / "backups").exists())

    def test_foreign_keys_are_enforced_on_each_connection(self):
        for _ in range(2):
            with closing(connect_database(self.database_path)) as connection:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("""
                        INSERT INTO planned_tasks (user_id, title, category)
                        VALUES (999, 'Invalid owner', 'Reading')
                    """)
                connection.rollback()
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("INSERT INTO fitness_details (activity_id) VALUES (999)")
                connection.rollback()

    def test_deleting_activity_reopens_task_and_cleans_linked_details(self):
        self.add_users()
        activity_id = save_activity(self.database_path, self.activity, user_id=1)
        other_id = save_activity(self.database_path, {**self.activity, "title": "Keep this"}, user_id=1)
        with closing(connect_database(self.database_path)) as connection:
            task_id = connection.execute("""
                INSERT INTO planned_tasks (user_id, title, category, activity_id)
                VALUES (1, 'Planned balance', 'Fitness', ?)
            """, (activity_id,)).lastrowid
            habit_id = connection.execute("""
                INSERT INTO habits (user_id, title, category, weekdays, start_date)
                VALUES (1, 'Daily balance', 'Fitness', '0,1,2,3,4,5,6', '2026-09-28')
            """).lastrowid
            connection.execute("""
                INSERT INTO habit_completions (user_id, habit_id, occurrence_date, activity_id)
                VALUES (1, ?, '2026-09-28', ?)
            """, (habit_id, activity_id))
            connection.executemany(
                "INSERT INTO fitness_details (activity_id, exercise_type) VALUES (?, 'Balance')",
                [(activity_id,), (other_id,)],
            )
            connection.commit()

        delete_activity(self.database_path, activity_id, user_id=1)
        with closing(connect_database(self.database_path)) as connection:
            task = connection.execute("SELECT * FROM planned_tasks WHERE id = ?", (task_id,)).fetchone()
            self.assertIsNone(task["activity_id"])
            self.assertEqual(task["cancelled"], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM habit_completions").fetchone()[0], 0)
            self.assertIsNotNone(connection.execute("SELECT * FROM habits WHERE id = ?", (habit_id,)).fetchone())
            self.assertEqual([row[0] for row in connection.execute("SELECT activity_id FROM fitness_details")], [other_id])
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertIsNotNone(get_activity(self.database_path, other_id, user_id=1))

    def test_deleting_a_habit_preserves_its_completed_journal_entry(self):
        self.add_users()
        activity_id = save_activity(self.database_path, self.activity, user_id=1)
        with closing(connect_database(self.database_path)) as connection:
            habit_id = connection.execute("""
                INSERT INTO habits (user_id, title, category, weekdays, start_date)
                VALUES (1, 'Daily balance', 'Fitness', '0', '2026-09-28')
            """).lastrowid
            connection.execute("""
                INSERT INTO habit_completions (user_id, habit_id, occurrence_date, activity_id)
                VALUES (1, ?, '2026-09-28', ?)
            """, (habit_id, activity_id))
            connection.commit()
            connection.execute("DELETE FROM habits WHERE id = ?", (habit_id,))
            connection.commit()
            self.assertEqual(connection.execute("SELECT count(*) FROM habit_completions").fetchone()[0], 0)
        self.assertIsNotNone(get_activity(self.database_path, activity_id, user_id=1))

    def test_activity_helpers_filter_every_read_update_delete_and_progress_by_owner(self):
        self.add_users()
        first_id = save_activity(self.database_path, self.activity, user_id=1)
        second_id = save_activity(self.database_path, {
            **self.activity, "title": "Second account", "activity_date": "2026-09-29",
        }, user_id=2)
        legacy_id = save_activity(self.database_path, {**self.activity, "title": "Unowned"})
        self.assertEqual([row["id"] for row in list_activities(self.database_path, 1)], [first_id])
        self.assertEqual([row["id"] for row in list_activities(self.database_path, 2)], [second_id])
        self.assertEqual([row["id"] for row in list_activities(self.database_path)], [legacy_id])
        self.assertIsNone(get_activity(self.database_path, second_id, 1))
        self.assertIsNone(get_activity(self.database_path, first_id, 2))
        update_activity(self.database_path, second_id, {**self.activity, "title": "Forbidden"}, 1)
        delete_activity(self.database_path, second_id, 1)
        self.assertEqual(get_activity(self.database_path, second_id, 2)["title"], "Second account")
        start, end = date(2026, 9, 28), date(2026, 10, 4)
        self.assertEqual(get_growth_dates(self.database_path, start, end, 1), {"2026-09-28"})
        self.assertEqual(get_growth_dates(self.database_path, start, end, 2), {"2026-09-29"})


if __name__ == "__main__":
    unittest.main()
