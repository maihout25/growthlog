import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, abort, redirect, render_template, request, session, url_for
from werkzeug.exceptions import SecurityError

from administration import init_commands
from auth import get_user_id
from configuration import configure_hosting
from database import (
    delete_activity, get_activity, get_growth_dates, list_activities,
    save_activity, update_activity,
)


app = Flask(__name__)
app.config.update(
    CSRF_ENABLED=True, LOGIN_DISABLED=False,
    MAX_CONTENT_LENGTH=1024 * 1024,
)
configure_hosting(app)

LOCAL_TIMEZONE = ZoneInfo("Africa/Dar_es_Salaam")
CATEGORIES = ("Reading", "Coding", "Fitness", "Other")
WEEKLY_GOAL = 5
ACTIVITY_FIELDS = (
    "activity_date", "title", "category", "duration_minutes", "what_i_did", "reflection",
)


def local_today():
    return datetime.now(LOCAL_TIMEZONE).date()


def validate_activity(form, today):
    """Return useful messages instead of saving incomplete or invalid data."""
    errors = []

    try:
        activity_date = date.fromisoformat(form["activity_date"])
        if activity_date > today:
            errors.append("Completed activities cannot have a future date.")
    except ValueError:
        errors.append("Enter a valid activity date.")

    if not form["title"]:
        errors.append("Enter a title.")

    if form["category"] not in CATEGORIES:
        errors.append("Choose a category from the list.")

    try:
        duration = int(form["duration_minutes"])
        if not 1 <= duration <= 1440:
            errors.append("Duration must be between 1 and 1,440 minutes.")
    except ValueError:
        errors.append("Enter duration as a whole number of minutes.")

    if not form["what_i_did"]:
        errors.append("Describe what you did.")

    if not form["reflection"]:
        errors.append("Add what you learned or improved.")

    return errors


@app.route("/")
def home():
    today = local_today()
    # weekday() is 0 on Monday and 6 on Sunday.
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    # Stop at today so a future date can never contribute to progress.
    growth_dates = get_growth_dates(app.config["DATABASE"], week_start, today, get_user_id())
    growth_days = len(growth_dates)

    days = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        days.append({
            "date": day,
            "qualifies": day.isoformat() in growth_dates,
            "is_today": day == today,
            "is_future": day > today,
        })

    return render_template(
        "index.html", week_start=week_start, week_end=week_end,
        days=days, growth_days=growth_days, weekly_goal=WEEKLY_GOAL,
        progress_value=min(growth_days, WEEKLY_GOAL),
    )


@app.route("/journal")
def journal():
    activities = list_activities(app.config["DATABASE"], get_user_id())
    return render_template("journal.html", activities=activities)


@app.route("/activities/new", methods=["GET", "POST"])
def new_activity():
    today = local_today()
    form = {
        "activity_date": today.isoformat(),
        "title": "",
        "category": "",
        "duration_minutes": "",
        "what_i_did": "",
        "reflection": "",
    }
    errors = []

    if request.method == "POST":
        # Form values arrive as strings. Strip accidental surrounding spaces.
        form = {name: request.form.get(name, "").strip() for name in form}
        errors = validate_activity(form, today)

        if not errors:
            form["activity_date"] = date.fromisoformat(form["activity_date"]).isoformat()
            activity_id = save_activity(app.config["DATABASE"], form, get_user_id())
            # Redirect so refreshing the confirmation does not submit again.
            return redirect(url_for("activity_saved", activity_id=activity_id), code=303)

    return render_template(
        "activity_form.html", form=form, errors=errors,
        categories=CATEGORIES, today=today.isoformat(),
        form_title="Record a completed activity",
        form_action=url_for("new_activity"), submit_label="Save completed activity",
    ), 400 if errors else 200


@app.route("/activities/<int:activity_id>/edit", methods=["GET", "POST"])
def edit_activity(activity_id):
    activity = get_activity(app.config["DATABASE"], activity_id, get_user_id())
    if activity is None:
        abort(404)

    today = local_today()
    # Start with saved values. The URL identifies the row; the form edits its fields.
    form = {name: activity[name] for name in ACTIVITY_FIELDS}
    errors = []

    if request.method == "POST":
        form = {name: request.form.get(name, "").strip() for name in form}
        errors = validate_activity(form, today)

        if not errors:
            form["activity_date"] = date.fromisoformat(form["activity_date"]).isoformat()
            update_activity(app.config["DATABASE"], activity_id, form, get_user_id())
            return redirect(url_for("activity_saved", activity_id=activity_id), code=303)

    return render_template(
        "activity_form.html", form=form, errors=errors,
        categories=CATEGORIES, today=today.isoformat(),
        form_title="Edit a completed activity",
        form_action=url_for("edit_activity", activity_id=activity_id),
        submit_label="Save changes",
    ), 400 if errors else 200


@app.route("/activities/<int:activity_id>/saved")
def activity_saved(activity_id):
    activity = get_activity(app.config["DATABASE"], activity_id, get_user_id())
    if activity is None:
        abort(404)
    return render_template("activity_saved.html", activity=activity)


@app.route("/activities/<int:activity_id>/delete", methods=["GET", "POST"])
def confirm_delete_activity(activity_id):
    activity = get_activity(app.config["DATABASE"], activity_id, get_user_id())
    if activity is None:
        abort(404)

    if request.method == "POST":
        confirmation = session.get("delete_confirmation", {})
        submitted_token = request.form.get("confirmation_token", "")
        if (
            confirmation.get("activity_id") != activity_id
            or not submitted_token
            or not secrets.compare_digest(
                confirmation.get("token", "").encode(), submitted_token.encode()
            )
        ):
            abort(400, description="Please reopen the activity's delete confirmation and try again.")

        delete_activity(app.config["DATABASE"], activity_id, get_user_id())
        session.pop("delete_confirmation", None)
        return redirect(url_for("journal"), code=303)

    # GET only prepares the confirmation; it never deletes a saved activity.
    token = secrets.token_hex(32)
    session["delete_confirmation"] = {"activity_id": activity_id, "token": token}
    return render_template("activity_delete.html", activity=activity, confirmation_token=token)


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
@app.errorhandler(429)
def request_error(error):
    if isinstance(error, SecurityError):
        # An untrusted hostname has no URL adapter for the page's navigation links.
        return error.get_response()
    return render_template("error.html", error=error), error.code


# Feature modules keep this file focused on the original activity workflow.
import auth
import insights
import planner

auth.init_app(app)
insights.init_app(app)
planner.init_app(app)

init_commands(app)
