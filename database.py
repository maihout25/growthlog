import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def connect_database(database_path):
    """Open SQLite and safely upgrade an older GrowthLog database if needed."""
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=15)
    connection.row_factory = sqlite3.Row
    # SQLite requires this on each connection for linked record cleanup.
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        if connection.execute("PRAGMA user_version").fetchone()[0] < 1:
            migrate_database(connection, database_path)
    except Exception:
        connection.rollback()
        connection.close()
        raise
    return connection


def migrate_database(connection, database_path):
    """Add accounts and new tables without replacing the existing journal."""
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(activities)")}
    if columns and "user_id" not in columns:
        backup_directory = database_path.parent / "backups"
        backup_directory.mkdir(exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        backup_path = backup_directory / f"growthlog-before-accounts-{timestamp}.sqlite3"
        # SQLite's backup API safely copies a database even if the app is running.
        with closing(sqlite3.connect(backup_path)) as backup:
            connection.backup(backup)

    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    connection.execute("BEGIN IMMEDIATE")
    for statement in schema.split(";"):
        if statement.strip():
            connection.execute(statement)
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(activities)")}
    if "user_id" not in columns:
        connection.execute("ALTER TABLE activities ADD COLUMN user_id INTEGER REFERENCES users(id)")
    connection.execute("CREATE INDEX IF NOT EXISTS activities_user_date ON activities(user_id, activity_date)")
    connection.execute("CREATE INDEX IF NOT EXISTS tasks_user_date ON planned_tasks(user_id, planned_date)")
    connection.execute("CREATE INDEX IF NOT EXISTS habits_user ON habits(user_id)")
    connection.execute("PRAGMA user_version = 1")
    connection.commit()


def save_activity(database_path, form, user_id=None):
    with closing(connect_database(database_path)) as connection:
        # Placeholders keep the submitted text separate from the SQL command.
        cursor = connection.execute("""
            INSERT INTO activities
                (activity_date, title, category, duration_minutes, what_i_did, reflection, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            form["activity_date"], form["title"], form["category"],
            int(form["duration_minutes"]), form["what_i_did"], form["reflection"], user_id,
        ))
        connection.commit()
        return cursor.lastrowid


def get_activity(database_path, activity_id, user_id=None):
    with closing(connect_database(database_path)) as connection:
        return connection.execute(
            "SELECT * FROM activities WHERE id = ? AND user_id IS ?", (activity_id, user_id)
        ).fetchone()


def list_activities(database_path, user_id=None):
    """Read this user's completed activities, newest activity dates first."""
    with closing(connect_database(database_path)) as connection:
        return connection.execute("""
            SELECT * FROM activities WHERE user_id IS ?
            ORDER BY activity_date DESC, id DESC
        """, (user_id,)).fetchall()


def update_activity(database_path, activity_id, form, user_id=None):
    """Update the chosen activity while keeping its original ID."""
    with closing(connect_database(database_path)) as connection:
        connection.execute("""
            UPDATE activities
            SET activity_date = ?, title = ?, category = ?, duration_minutes = ?,
                what_i_did = ?, reflection = ?
            WHERE id = ? AND user_id IS ?
        """, (
            form["activity_date"], form["title"], form["category"],
            int(form["duration_minutes"]), form["what_i_did"], form["reflection"],
            activity_id, user_id,
        ))
        connection.commit()


def delete_activity(database_path, activity_id, user_id=None):
    """Permanently remove only the activity with this ID."""
    with closing(connect_database(database_path)) as connection:
        connection.execute(
            "DELETE FROM activities WHERE id = ? AND user_id IS ?", (activity_id, user_id)
        )
        connection.commit()


def get_growth_dates(database_path, start_date, end_date, user_id=None):
    """Return unique dates that have a completed activity with a reflection."""
    with closing(connect_database(database_path)) as connection:
        rows = connection.execute("""
            SELECT activity_date, reflection FROM activities
            WHERE user_id IS ? AND activity_date BETWEEN ? AND ?
        """, (user_id, start_date.isoformat(), end_date.isoformat())).fetchall()

    # A set keeps each date only once. Whitespace alone is not a reflection.
    return {row["activity_date"] for row in rows if row["reflection"].strip()}
