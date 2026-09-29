"""Planned tasks, recurring habits, and reminders for the local app.

A plan is not a completed activity. Completing one creates a journal entry with
a reflection; the dashboard continues to count only those journal entries.
"""

from contextlib import closing
from datetime import date, datetime, time, timedelta

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, url_for

from auth import get_user_id
from database import connect_database


planner = Blueprint("planner", __name__)
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
REMINDERS = (("", "No reminder"), ("0", "At the scheduled time"),
             ("5", "5 minutes before"), ("15", "15 minutes before"),
             ("30", "30 minutes before"), ("60", "1 hour before"),
             ("1440", "1 day before"))
ACTIVITY_FIELDS = ("activity_date", "title", "category", "duration_minutes", "what_i_did", "reflection")


def init_app(app):
    app.register_blueprint(planner)


def database():
    return closing(connect_database(current_app.config["DATABASE"]))


def today():
    # Delayed imports avoid a circular import while app.py registers blueprints.
    from app import local_today
    return local_today()


def local_now():
    from app import LOCAL_TIMEZONE
    return datetime.now(LOCAL_TIMEZONE)


def get_owned(connection, table, record_id):
    # The table name comes only from these two fixed choices, never form input.
    if table not in ("planned_tasks", "habits"):
        raise ValueError("Unknown plan type")
    row = connection.execute(
        f"SELECT * FROM {table} WHERE id = ? AND user_id = ?",
        (record_id, get_user_id()),
    ).fetchone()
    if row is None:
        abort(404)
    return row


def read_plan_form(record=None, habit=False):
    values = {
        "title": "", "category": "", "notes": "", "planned_date": "",
        "planned_time": "", "reminder_minutes": "", "start_date": today().isoformat(),
        "end_date": "", "weekdays": [],
    }
    if record is not None:
        for key in values:
            if key in record.keys():
                values[key] = record[key] if record[key] is not None else ""
        if habit:
            values["weekdays"] = str(record["weekdays"]).split(",")
    if request.method == "POST":
        for key in values:
            values[key] = request.form.get(key, "").strip()
        values["weekdays"] = request.form.getlist("weekdays") if habit else []
    return values


def validate_plan(form, habit=False):
    from app import CATEGORIES
    errors = []
    if not form["title"] or len(form["title"]) > 200:
        errors.append("Enter a title of 1 to 200 characters.")
    if form["category"] not in CATEGORIES:
        errors.append("Choose a category from the list.")
    if len(form["notes"]) > 10000:
        errors.append("Keep notes within 10,000 characters.")

    date_fields = ("start_date", "end_date") if habit else ("planned_date",)
    for field in date_fields:
        if form[field]:
            try:
                form[field] = date.fromisoformat(form[field]).isoformat()
            except ValueError:
                errors.append(f"Enter a valid {field.replace('_', ' ')}.")
        elif field == "start_date":
            errors.append("Choose the habit's start date.")
    if habit:
        if not form["weekdays"] or any(day not in [str(n) for n in range(7)] for day in form["weekdays"]):
            errors.append("Choose at least one valid weekday.")
        else:
            form["weekdays"] = sorted(set(form["weekdays"]))
        if form["end_date"] and form["end_date"] < form["start_date"]:
            errors.append("The end date must be on or after the start date.")

    if form["planned_time"]:
        try:
            parsed = time.fromisoformat(form["planned_time"])
            if parsed.tzinfo is not None or len(form["planned_time"]) != 5:
                raise ValueError
            form["planned_time"] = parsed.strftime("%H:%M")
        except ValueError:
            errors.append("Enter a valid time as hours and minutes.")
    if form["reminder_minutes"] not in {value for value, label in REMINDERS}:
        errors.append("Choose a reminder from the list.")
    if form["reminder_minutes"] != "" and (not form["planned_time"] or (not habit and not form["planned_date"])):
        errors.append("A reminder needs a scheduled date and time.")
    return errors


def render_plan_form(form, errors, habit=False, editing=False):
    from app import CATEGORIES
    return render_template(
        "planner/plan_form.html", form=form, errors=errors, habit=habit,
        editing=editing, categories=CATEGORIES, weekdays=WEEKDAYS, reminders=REMINDERS,
    ), 400 if errors else 200


@planner.route("/planner")
def index():
    with database() as connection:
        tasks = connection.execute("""
            SELECT * FROM planned_tasks WHERE user_id = ?
            ORDER BY activity_id IS NOT NULL, cancelled,
                     planned_date IS NULL, planned_date, planned_time, id DESC
        """, (get_user_id(),)).fetchall()
        habits = connection.execute("""
            SELECT * FROM habits WHERE user_id = ? ORDER BY active DESC, title, id
        """, (get_user_id(),)).fetchall()
    return render_template("planner/index.html", tasks=tasks, habits=habits, weekdays=WEEKDAYS, today=today().isoformat())


@planner.route("/tasks/new", methods=["GET", "POST"])
def new_task():
    form = read_plan_form()
    errors = validate_plan(form) if request.method == "POST" else []
    if request.method == "POST" and not errors:
        with database() as connection:
            connection.execute("""
                INSERT INTO planned_tasks
                (user_id, title, category, notes, planned_date, planned_time, reminder_minutes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (get_user_id(), form["title"], form["category"], form["notes"],
                  form["planned_date"] or None, form["planned_time"] or None,
                  int(form["reminder_minutes"]) if form["reminder_minutes"] else None))
            connection.commit()
        return redirect(url_for("planner.index"), code=303)
    return render_plan_form(form, errors)


@planner.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
def edit_task(task_id):
    with database() as connection:
        task = get_owned(connection, "planned_tasks", task_id)
        form = read_plan_form(task)
        errors = validate_plan(form) if request.method == "POST" else []
        if request.method == "POST" and not errors:
            connection.execute("""
                UPDATE planned_tasks SET title = ?, category = ?, notes = ?,
                    planned_date = ?, planned_time = ?, reminder_minutes = ?
                WHERE id = ? AND user_id = ?
            """, (form["title"], form["category"], form["notes"], form["planned_date"] or None,
                  form["planned_time"] or None,
                  int(form["reminder_minutes"]) if form["reminder_minutes"] else None,
                  task_id, get_user_id()))
            connection.commit()
            return redirect(url_for("planner.index"), code=303)
    return render_plan_form(form, errors, editing=True)


@planner.route("/tasks/<int:task_id>/delete", methods=["GET", "POST"])
def delete_task(task_id):
    with database() as connection:
        task = get_owned(connection, "planned_tasks", task_id)
        if request.method == "POST":
            if request.form.get("confirm") != "delete":
                abort(400, description="Confirm that you want to delete this plan.")
            connection.execute("DELETE FROM planned_tasks WHERE id = ? AND user_id = ?", (task_id, get_user_id()))
            connection.commit()
            return redirect(url_for("planner.index"), code=303)
    return render_template("planner/delete_task.html", task=task)


def completion_form(record):
    values = dict.fromkeys(ACTIVITY_FIELDS, "")
    values.update(activity_date=today().isoformat(), title=record["title"], category=record["category"], what_i_did=record["notes"])
    if request.method == "POST":
        values = {key: request.form.get(key, "").strip() for key in ACTIVITY_FIELDS}
    return values


def insert_completion(connection, form):
    cursor = connection.execute("""
        INSERT INTO activities
        (user_id, activity_date, title, category, duration_minutes, what_i_did, reflection)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (get_user_id(), date.fromisoformat(form["activity_date"]).isoformat(),
          form["title"], form["category"], int(form["duration_minutes"]),
          form["what_i_did"], form["reflection"]))
    return cursor.lastrowid


def render_completion(record, form, errors, occurrence=None):
    from app import CATEGORIES
    return render_template("planner/complete.html", record=record, form=form,
                           errors=errors, occurrence=occurrence,
                           today=today().isoformat(), categories=CATEGORIES), 400 if errors else 200


@planner.route("/tasks/<int:task_id>/complete", methods=["GET", "POST"])
def complete_task(task_id):
    from app import validate_activity
    with database() as connection:
        # Taking the write lock before checking prevents duplicate journal entries.
        if request.method == "POST":
            connection.execute("BEGIN IMMEDIATE")
        task = get_owned(connection, "planned_tasks", task_id)
        if task["activity_id"]:
            return redirect(url_for("activity_saved", activity_id=task["activity_id"]), code=303)
        if task["cancelled"]:
            abort(400, description="This task has been cancelled.")
        form = completion_form(task)
        errors = validate_activity(form, today()) if request.method == "POST" else []
        if request.method == "POST" and not errors:
            activity_id = insert_completion(connection, form)
            connection.execute("""
                UPDATE planned_tasks SET activity_id = ? WHERE id = ? AND user_id = ?
            """, (activity_id, task_id, get_user_id()))
            connection.commit()
            return redirect(url_for("activity_saved", activity_id=activity_id), code=303)
    return render_completion(task, form, errors)


@planner.route("/habits/new", methods=["GET", "POST"])
def new_habit():
    form = read_plan_form(habit=True)
    errors = validate_plan(form, habit=True) if request.method == "POST" else []
    if request.method == "POST" and not errors:
        with database() as connection:
            connection.execute("""
                INSERT INTO habits
                (user_id, title, category, notes, weekdays, start_date, end_date, planned_time, reminder_minutes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (get_user_id(), form["title"], form["category"], form["notes"],
                  ",".join(form["weekdays"]), form["start_date"], form["end_date"] or None,
                  form["planned_time"] or None,
                  int(form["reminder_minutes"]) if form["reminder_minutes"] else None))
            connection.commit()
        return redirect(url_for("planner.index"), code=303)
    return render_plan_form(form, errors, habit=True)


@planner.route("/habits/<int:habit_id>/edit", methods=["GET", "POST"])
def edit_habit(habit_id):
    with database() as connection:
        habit = get_owned(connection, "habits", habit_id)
        form = read_plan_form(habit, habit=True)
        errors = validate_plan(form, habit=True) if request.method == "POST" else []
        if request.method == "POST" and not errors:
            connection.execute("""
                UPDATE habits SET title = ?, category = ?, notes = ?, weekdays = ?,
                    start_date = ?, end_date = ?, planned_time = ?, reminder_minutes = ?
                WHERE id = ? AND user_id = ?
            """, (form["title"], form["category"], form["notes"], ",".join(form["weekdays"]),
                  form["start_date"], form["end_date"] or None, form["planned_time"] or None,
                  int(form["reminder_minutes"]) if form["reminder_minutes"] else None,
                  habit_id, get_user_id()))
            connection.commit()
            return redirect(url_for("planner.index"), code=303)
    return render_plan_form(form, errors, habit=True, editing=True)


@planner.route("/habits/<int:habit_id>/archive", methods=["POST"])
def archive_habit(habit_id):
    with database() as connection:
        habit = get_owned(connection, "habits", habit_id)
        connection.execute("UPDATE habits SET active = ? WHERE id = ? AND user_id = ?", (0 if habit["active"] else 1, habit_id, get_user_id()))
        connection.commit()
    return redirect(url_for("planner.index"), code=303)


def habit_occurs(habit, day):
    return bool(habit["active"] and habit["start_date"] <= day.isoformat()
                and (not habit["end_date"] or day.isoformat() <= habit["end_date"])
                and str(day.weekday()) in habit["weekdays"].split(","))


@planner.route("/habits/<int:habit_id>/complete/<occurrence_date>", methods=["GET", "POST"])
def complete_habit(habit_id, occurrence_date):
    from app import validate_activity
    try:
        occurrence = date.fromisoformat(occurrence_date)
    except ValueError:
        abort(404)
    with database() as connection:
        if request.method == "POST":
            connection.execute("BEGIN IMMEDIATE")
        habit = get_owned(connection, "habits", habit_id)
        previous = connection.execute("""
            SELECT activity_id FROM habit_completions
            WHERE habit_id = ? AND occurrence_date = ? AND user_id = ?
        """, (habit_id, occurrence.isoformat(), get_user_id())).fetchone()
        if previous:
            return redirect(url_for("activity_saved", activity_id=previous["activity_id"]), code=303)
        if occurrence > today() or not habit_occurs(habit, occurrence):
            abort(400, description="Choose a scheduled habit date that is today or earlier.")
        form = completion_form(habit)
        if request.method == "GET":
            form["activity_date"] = occurrence.isoformat()
        errors = validate_activity(form, today()) if request.method == "POST" else []
        if request.method == "POST" and not errors:
            activity_id = insert_completion(connection, form)
            connection.execute("""
                INSERT INTO habit_completions (user_id, habit_id, occurrence_date, activity_id)
                VALUES (?, ?, ?, ?)
            """, (get_user_id(), habit_id, occurrence.isoformat(), activity_id))
            connection.commit()
            return redirect(url_for("activity_saved", activity_id=activity_id), code=303)
    return render_completion(habit, form, errors, occurrence=occurrence)


def selected_week():
    try:
        day = date.fromisoformat(request.args.get("week", today().isoformat()))
        monday = day - timedelta(days=day.weekday())
        # Leave room for navigation and a complete week at the date boundaries.
        if not date(1900, 1, 8) <= monday <= date(9999, 12, 20):
            raise ValueError
        return monday
    except (ValueError, OverflowError):
        abort(400, description="Choose a valid week between 1900 and 9999.")


@planner.route("/schedule")
def schedule():
    start = selected_week()
    end = start + timedelta(days=6)
    with database() as connection:
        tasks = connection.execute("""
            SELECT * FROM planned_tasks WHERE user_id = ? AND cancelled = 0
                AND planned_date BETWEEN ? AND ? ORDER BY planned_time, title
        """, (get_user_id(), start.isoformat(), end.isoformat())).fetchall()
        habits = connection.execute("SELECT * FROM habits WHERE user_id = ? ORDER BY planned_time, title", (get_user_id(),)).fetchall()
        completed = connection.execute("""
            SELECT hc.*, a.activity_date FROM habit_completions hc
            JOIN activities a ON a.id = hc.activity_id AND a.user_id = hc.user_id
            WHERE hc.user_id = ? AND hc.occurrence_date BETWEEN ? AND ?
        """, (get_user_id(), start.isoformat(), end.isoformat())).fetchall()
    completed_lookup = {(row["habit_id"], row["occurrence_date"]): row for row in completed}
    days = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        occurrences = []
        for habit in habits:
            completion = completed_lookup.get((habit["id"], day.isoformat()))
            if habit_occurs(habit, day) or completion:
                occurrences.append({"habit": habit, "completion": completion})
        days.append({"date": day, "tasks": [task for task in tasks if task["planned_date"] == day.isoformat()], "habits": occurrences})
    return render_template("planner/schedule.html", days=days, start=start, end=end,
                           previous_week=start - timedelta(days=7), next_week=start + timedelta(days=7), today=today())


def due_reminders():
    now = local_now()
    first = now.date()
    last = first + timedelta(days=1)
    with database() as connection:
        tasks = connection.execute("""
            SELECT * FROM planned_tasks WHERE user_id = ? AND activity_id IS NULL
                AND cancelled = 0 AND reminder_minutes IS NOT NULL AND planned_time IS NOT NULL
                AND planned_date BETWEEN ? AND ?
        """, (get_user_id(), first.isoformat(), last.isoformat())).fetchall()
        habits = connection.execute("""
            SELECT * FROM habits WHERE user_id = ? AND active = 1
                AND reminder_minutes IS NOT NULL AND planned_time IS NOT NULL
        """, (get_user_id(),)).fetchall()
        completed = {(row["habit_id"], row["occurrence_date"]) for row in connection.execute("""
            SELECT habit_id, occurrence_date FROM habit_completions
            WHERE user_id = ? AND occurrence_date BETWEEN ? AND ?
        """, (get_user_id(), first.isoformat(), last.isoformat()))}
        dismissed = {row["reminder_key"] for row in connection.execute(
            "SELECT reminder_key FROM reminder_dismissals WHERE user_id = ?", (get_user_id(),))}

    candidates = [("task", task, date.fromisoformat(task["planned_date"])) for task in tasks]
    for habit in habits:
        for day in (first, last):
            if habit_occurs(habit, day) and (habit["id"], day.isoformat()) not in completed:
                candidates.append(("habit", habit, day))

    reminders = []
    for kind, record, day in candidates:
        scheduled = datetime.combine(day, time.fromisoformat(record["planned_time"]), tzinfo=now.tzinfo)
        due = scheduled - timedelta(minutes=record["reminder_minutes"])
        key = f"{kind}:{record['id']}:{day.isoformat()}:{record['planned_time']}:{record['reminder_minutes']}"
        if due <= now and key not in dismissed:
            # Future habit occurrences can be viewed but cannot yet be completed.
            href = (url_for("planner.complete_task", task_id=record["id"]) if kind == "task"
                    else url_for("planner.schedule", week=day.isoformat()))
            reminders.append({"reminder_key": key, "title": record["title"],
                              "when": scheduled.strftime("%a %d %b, %H:%M"), "href": href})
    return reminders


@planner.route("/api/reminders")
def reminders():
    response = jsonify(reminders=due_reminders())
    response.headers["Cache-Control"] = "no-store"
    return response


@planner.route("/api/reminders/dismiss", methods=["POST"])
def dismiss_reminder():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        abort(400)
    key = payload.get("reminder_key", "")
    if not isinstance(key, str) or key not in {item["reminder_key"] for item in due_reminders()}:
        abort(400, description="This reminder is no longer due.")
    with database() as connection:
        connection.execute("INSERT OR IGNORE INTO reminder_dismissals (user_id, reminder_key) VALUES (?, ?)", (get_user_id(), key))
        connection.commit()
    return jsonify(ok=True)
