"""Accounts, signed sessions, and protection for submitted forms."""

import re
import secrets
import sqlite3
from contextlib import closing
from functools import wraps

from flask import (
    Blueprint, abort, current_app, g, redirect, render_template,
    request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database import connect_database
from login_throttle import LoginThrottle


auth = Blueprint("auth", __name__)
PUBLIC_ENDPOINTS = {"auth.setup", "auth.login", "auth.register", "static"}


def login_is_disabled():
    """Only isolated tests may bypass account ownership."""
    return current_app.testing and current_app.config.get("LOGIN_DISABLED", False)


def get_user_id():
    if login_is_disabled():
        return None
    if g.get("user") is None:
        abort(401)
    return g.user["id"]


def csrf_token():
    """Give this browser a random token to include in every submitted form."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not login_is_disabled() and g.get("user") is None:
            return redirect(url_for("auth.login"), code=303)
        return view(*args, **kwargs)
    return wrapped


def init_app(app):
    app.config.setdefault("CSRF_ENABLED", True)
    app.config.setdefault("LOGIN_DISABLED", False)
    app.config.setdefault("ALLOW_REGISTRATION", True)
    app.register_blueprint(auth)
    login_throttle = LoginThrottle()

    @app.before_request
    def load_account_and_protect_forms():
        g.user = None
        # Let Flask report invalid hosts and missing routes before login redirects.
        if request.routing_exception is not None:
            return
        # The original learning checks use a temporary database without accounts.
        if not login_is_disabled() and request.endpoint != "static":
            with closing(connect_database(app.config["DATABASE"])) as connection:
                g.has_users = connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
                user_id = session.get("user_id")
                if user_id is not None:
                    g.user = connection.execute(
                        "SELECT id, username FROM users WHERE id = ?", (user_id,)
                    ).fetchone()
                    if g.user is None:
                        session.clear()

            if request.endpoint not in PUBLIC_ENDPOINTS and g.user is None:
                destination = "auth.setup" if not g.has_users and app.config["ALLOW_REGISTRATION"] else "auth.login"
                return redirect(url_for(destination), code=303)

        if request.method not in {"GET", "HEAD", "OPTIONS"} and app.config["CSRF_ENABLED"]:
            expected = session.get("csrf_token", "")
            submitted = request.form.get("csrf_token") or request.headers.get("X-CSRFToken", "")
            if not expected or not submitted or not secrets.compare_digest(
                expected.encode(), submitted.encode()
            ):
                abort(400, description="This form expired. Refresh the page and submit it again.")

        if app.config.get("PRODUCTION") and request.endpoint == "auth.login" and request.method == "POST":
            if not login_throttle.allow(request.form.get("username", "")):
                abort(429, description="Too many sign-in attempts. Please wait 15 minutes and try again.")

    @app.context_processor
    def account_template_values():
        return {"current_user": g.get("user"), "csrf_token": csrf_token}

    @app.after_request
    def prevent_private_page_caching(response):
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; object-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'self'"
        )
        if app.config.get("PRODUCTION"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response


def validate_registration(username, password, confirmation):
    errors = []
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", username):
        errors.append("Use 1 to 40 letters, numbers, dots, underscores, or hyphens for your username.")
    errors.extend(validate_password(password, confirmation))
    return errors


def validate_password(password, confirmation):
    errors = []
    if len(password) < 10:
        errors.append("Choose a password with at least 10 characters.")
    if len(password) > 256:
        errors.append("Keep your password to 256 characters or fewer.")
    if password != confirmation:
        errors.append("The passwords do not match.")
    return errors


def start_session(user_id):
    # A new sign-in also replaces any tokens or confirmations from the old session.
    session.clear()
    session["user_id"] = user_id


def register_account(first_account):
    if not current_app.config["ALLOW_REGISTRATION"]:
        abort(403, description="Account registration is closed. Contact the owner for an account.")
    username = ""
    errors = []
    if first_account and g.has_users:
        return redirect(url_for("home" if g.user else "auth.login"), code=303)
    if not first_account and not g.has_users:
        return redirect(url_for("auth.setup"), code=303)
    if g.user is not None:
        return redirect(url_for("home"), code=303)

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirmation = request.form.get("password_confirmation", "")
        errors = validate_registration(username, password, confirmation)
        if not errors:
            password_hash = generate_password_hash(password)
            with closing(connect_database(current_app.config["DATABASE"])) as connection:
                try:
                    # Lock before checking: only one browser can create the first account.
                    connection.execute("BEGIN IMMEDIATE")
                    has_users = connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
                    if first_account and has_users:
                        connection.rollback()
                        return redirect(url_for("auth.login"), code=303)
                    if not first_account and not has_users:
                        connection.rollback()
                        return redirect(url_for("auth.setup"), code=303)
                    cursor = connection.execute(
                        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                        (username, password_hash),
                    )
                    user_id = cursor.lastrowid
                    if first_account:
                        connection.execute(
                            "UPDATE activities SET user_id = ? WHERE user_id IS NULL", (user_id,)
                        )
                    connection.commit()
                except sqlite3.IntegrityError:
                    connection.rollback()
                    errors.append("That username is already in use. Choose another one.")
            if not errors:
                start_session(user_id)
                return redirect(url_for("home"), code=303)

    return render_template(
        "auth/register.html", first_account=first_account, username=username, errors=errors,
    ), 400 if errors else 200


@auth.route("/setup", methods=["GET", "POST"])
def setup():
    return register_account(first_account=True)


@auth.route("/register", methods=["GET", "POST"])
def register():
    return register_account(first_account=False)


@auth.route("/login", methods=["GET", "POST"])
def login():
    if not g.has_users and current_app.config["ALLOW_REGISTRATION"]:
        return redirect(url_for("auth.setup"), code=303)
    if g.user is not None:
        return redirect(url_for("home"), code=303)

    username = ""
    errors = []
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with closing(connect_database(current_app.config["DATABASE"])) as connection:
            user = connection.execute(
                "SELECT id, password_hash FROM users WHERE username = ?", (username,)
            ).fetchone()
        if user is None or len(password) > 256 or not check_password_hash(user["password_hash"], password):
            errors.append("The username or password is incorrect.")
        else:
            start_session(user["id"])
            return redirect(url_for("home"), code=303)

    return render_template("auth/login.html", username=username, errors=errors), 400 if errors else 200


@auth.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"), code=303)


@auth.route("/account", methods=["GET", "POST"])
def account():
    errors = []
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        password = request.form.get("password", "")
        confirmation = request.form.get("password_confirmation", "")
        errors = validate_password(password, confirmation)
        with closing(connect_database(current_app.config["DATABASE"])) as connection:
            user = connection.execute(
                "SELECT password_hash FROM users WHERE id = ?", (get_user_id(),)
            ).fetchone()
            if len(current_password) > 256 or not check_password_hash(user["password_hash"], current_password):
                errors.append("Your current password is incorrect.")
            if not errors:
                connection.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (generate_password_hash(password), get_user_id()),
                )
                connection.commit()
                start_session(get_user_id())
                return redirect(url_for("auth.account", changed="1"), code=303)

    return render_template(
        "auth/account.html", errors=errors, changed=request.args.get("changed") == "1",
    ), 400 if errors else 200
