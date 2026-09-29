"""Optional workout details and a place to reflect on each week."""

import math
from contextlib import closing
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for

from auth import get_user_id
from database import connect_database


blueprint = Blueprint("insights", __name__)
FITNESS_FIELDS = ("exercise_type", "sets", "reps", "weight_kg", "distance_km", "notes")
REFLECTION_FIELDS = ("wins", "challenges", "next_week")


def init_app(app):
    app.register_blueprint(blueprint)


def local_today():
    return datetime.now(ZoneInfo("Africa/Dar_es_Salaam")).date()


def monday_for(day):
    return day - timedelta(days=day.weekday())


def read_week(value):
    """A reflection belongs to a Monday, never to a future week."""
    try:
        week = date.fromisoformat(value)
    except ValueError:
        abort(404)
    if week.isoformat() != value or week.weekday() != 0 or week > monday_for(local_today()):
        abort(404)
    return week


def validate_fitness(form):
    """Keep blank measurements optional, but reject invalid numbers."""
    values = dict(form)
    errors = []
    for name in ("sets", "reps"):
        values[name] = None
        if form[name]:
            try:
                number = int(form[name])
                if number < 1 or number > 2**63 - 1:
                    raise ValueError
                values[name] = number
            except ValueError:
                errors.append(f"Enter a valid positive whole number for {name}.")
    for name, label in (("weight_kg", "Weight"), ("distance_km", "Distance")):
        values[name] = None
        if form[name]:
            try:
                number = float(form[name])
                if not math.isfinite(number) or number < 0:
                    raise ValueError
                values[name] = number
            except ValueError:
                errors.append(f"{label} must be a finite number of zero or more.")
    return values, errors


@blueprint.route("/activities/<int:activity_id>/fitness", methods=["GET", "POST"])
def fitness(activity_id):
    user_id = get_user_id()
    with closing(connect_database(current_app.config["DATABASE"])) as connection:
        activity = connection.execute("""
            SELECT * FROM activities WHERE id = ? AND user_id = ? AND category = 'Fitness'
        """, (activity_id, user_id)).fetchone()
        if activity is None:
            abort(404)
        details = connection.execute("""
            SELECT fitness_details.* FROM fitness_details
            JOIN activities ON activities.id = fitness_details.activity_id
            WHERE activities.id = ? AND activities.user_id = ?
        """, (activity_id, user_id)).fetchone()

        form = {name: "" if details is None or details[name] is None else str(details[name])
                for name in FITNESS_FIELDS}
        errors = []
        if request.method == "POST":
            form = {name: request.form.get(name, "").strip() for name in FITNESS_FIELDS}
            values, errors = validate_fitness(form)
            if not errors:
                if any(form.values()):
                    connection.execute("""
                        INSERT INTO fitness_details
                            (activity_id, exercise_type, sets, reps, weight_kg, distance_km, notes)
                        SELECT id, ?, ?, ?, ?, ?, ? FROM activities
                        WHERE id = ? AND user_id = ? AND category = 'Fitness'
                        ON CONFLICT(activity_id) DO UPDATE SET
                            exercise_type = excluded.exercise_type, sets = excluded.sets,
                            reps = excluded.reps, weight_kg = excluded.weight_kg,
                            distance_km = excluded.distance_km, notes = excluded.notes
                    """, (*[values[name] for name in FITNESS_FIELDS], activity_id, user_id))
                    message = "Fitness details saved."
                else:
                    connection.execute("""
                        DELETE FROM fitness_details WHERE activity_id IN (
                            SELECT id FROM activities WHERE id = ? AND user_id = ?
                        )
                    """, (activity_id, user_id))
                    message = "Fitness details cleared. Your completed activity is still saved."
                connection.commit()
                flash(message, "success")
                return redirect(url_for("insights.fitness", activity_id=activity_id), code=303)

    return render_template("insights/fitness.html", activity=activity, form=form, errors=errors), 400 if errors else 200


def weekly_summary(connection, user_id, week):
    """Read saved activities each time so edits and deletions are reflected."""
    end = min(week + timedelta(days=6), local_today())
    activities = connection.execute("""
        SELECT activity_date, duration_minutes, reflection FROM activities
        WHERE user_id = ? AND activity_date BETWEEN ? AND ?
    """, (user_id, week.isoformat(), end.isoformat())).fetchall()
    qualifying = [activity for activity in activities if activity["reflection"].strip()]
    return {
        "growth_days": len({activity["activity_date"] for activity in qualifying}),
        "activity_count": len(activities),
        "minutes": sum(activity["duration_minutes"] for activity in activities),
    }


@blueprint.route("/reflections")
def reflections():
    current_week = monday_for(local_today())
    errors = []
    # The picker accepts any day of a past or current week, then finds its Monday.
    selected_date = request.args.get("week", "").strip()
    if selected_date:
        try:
            selected_week = monday_for(date.fromisoformat(selected_date))
            if selected_week > current_week:
                raise ValueError
        except ValueError:
            errors.append("Choose a date in the current week or an earlier week.")
        else:
            return redirect(url_for("insights.weekly_reflection", week_start=selected_week.isoformat()))
    with closing(connect_database(current_app.config["DATABASE"])) as connection:
        saved = connection.execute("""
            SELECT * FROM weekly_reflections WHERE user_id = ? ORDER BY week_start DESC
        """, (get_user_id(),)).fetchall()
    return render_template(
        "insights/reflections.html", reflections=saved, current_week=current_week,
        today=local_today(), selected_date=selected_date, errors=errors,
    ), 400 if errors else 200


@blueprint.route("/reflections/<week_start>", methods=["GET", "POST"])
def weekly_reflection(week_start):
    week = read_week(week_start)
    user_id = get_user_id()
    with closing(connect_database(current_app.config["DATABASE"])) as connection:
        saved = connection.execute("""
            SELECT * FROM weekly_reflections WHERE user_id = ? AND week_start = ?
        """, (user_id, week_start)).fetchone()
        form = {name: saved[name] if saved else "" for name in REFLECTION_FIELDS}
        errors = []
        if request.method == "POST":
            form = {name: request.form.get(name, "").strip() for name in REFLECTION_FIELDS}
            if not any(form.values()):
                errors.append("Write something in at least one field before saving your reflection.")
            else:
                connection.execute("""
                    INSERT INTO weekly_reflections (user_id, week_start, wins, challenges, next_week)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, week_start) DO UPDATE SET
                        wins = excluded.wins, challenges = excluded.challenges, next_week = excluded.next_week
                """, (user_id, week_start, *[form[name] for name in REFLECTION_FIELDS]))
                connection.commit()
                flash("Weekly reflection saved.", "success")
                return redirect(url_for("insights.weekly_reflection", week_start=week_start), code=303)
        summary = weekly_summary(connection, user_id, week)

    return render_template(
        "insights/weekly_reflection.html", week_start=week, week_end=week + timedelta(days=6),
        form=form, errors=errors, saved=saved, summary=summary,
    ), 400 if errors else 200


@blueprint.route("/reflections/<week_start>/delete", methods=["GET", "POST"])
def delete_reflection(week_start):
    week = read_week(week_start)
    user_id = get_user_id()
    with closing(connect_database(current_app.config["DATABASE"])) as connection:
        saved = connection.execute("""
            SELECT * FROM weekly_reflections WHERE user_id = ? AND week_start = ?
        """, (user_id, week_start)).fetchone()
        if saved is None:
            abort(404)
        if request.method == "POST":
            if request.form.get("confirm") != "delete":
                abort(400, description="Use the confirmation button to delete this reflection.")
            connection.execute("""
                DELETE FROM weekly_reflections WHERE user_id = ? AND week_start = ?
            """, (user_id, week_start))
            connection.commit()
            flash("Weekly reflection deleted. Your completed activities are still saved.", "success")
            return redirect(url_for("insights.reflections"), code=303)
    return render_template("insights/reflection_delete.html", reflection=saved, week_start=week)
