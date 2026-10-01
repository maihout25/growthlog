"""Maintenance commands run from your computer or the host's private console."""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import click
from werkzeug.security import generate_password_hash

from auth import validate_registration
from database import connect_database


def init_commands(app):
    @app.cli.command("create-user")
    @click.option("--username", prompt=True)
    @click.password_option()
    def create_user(username, password):
        """Create an account without opening public sign-ups."""
        username = username.strip()
        errors = validate_registration(username, password, password)
        if errors:
            raise click.ClickException(" ".join(errors))
        password_hash = generate_password_hash(password)
        with closing(connect_database(app.config["DATABASE"])) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                first_account = connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None
                cursor = connection.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, password_hash),
                )
                if first_account:
                    connection.execute(
                        "UPDATE activities SET user_id = ? WHERE user_id IS NULL", (cursor.lastrowid,)
                    )
                connection.commit()
            except sqlite3.IntegrityError:
                connection.rollback()
                raise click.ClickException("That username is already in use.") from None
        click.echo(f"Created account: {username}")

    @app.cli.command("backup-db")
    def backup_database():
        """Save a consistent database copy, even while GrowthLog is running."""
        source = Path(app.config["DATABASE"])
        if not source.is_file():
            raise click.ClickException("No database exists yet. Create an account first.")
        directory = source.parent / "backups"
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        destination = directory / f"growthlog-{timestamp}.sqlite3"
        with closing(sqlite3.connect(source)) as connection:
            with closing(sqlite3.connect(destination)) as backup:
                connection.backup(backup)
        click.echo(f"Database backup saved to {destination}")
