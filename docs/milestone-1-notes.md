> Historical learning notes from milestone 1. Current setup instructions are in README.md.

# GrowthLog

A local personal growth app built one runnable increment at a time with Python,
Flask, SQLite, HTML, CSS, and plain JavaScript.

## Current progress

The first increment introduced a Flask homepage and basic CSS.
Increment 2 added a completed activity form and persistent SQLite storage.
Increment 3 added a journal listing saved activities and their reflections.
Increment 4 added editing from the journal, reusing the activity form.
Increment 5 added deletion with a confirmation page and a cancel option.
Increment 6 adds a weekly dashboard counting distinct growth days toward five.
Milestone 1 is implemented; later milestones remain out of scope.
No JavaScript is needed for these pages.

```text
growthlog/
  .venv/                 Project's Python environment (generated locally)
  app.py                 Flask routes, date handling, and form validation
  database.py            SQLite table and activity storage functions
  instance/
    growthlog.sqlite3     Your saved activities (created on first database use)
  templates/
    index.html           Weekly dashboard and homepage
    activity_form.html   Shared form for recording and editing activities
    activity_saved.html  Confirmation read from the database
    activity_delete.html Confirmation before permanently deleting an activity
    journal.html         List of completed activities and reflections
  static/
    style.css            Page styles
  tests/
    test_activities.py   Checks using a temporary database
    test_progress.py     Weekly boundaries, distinct dates, and recalculation checks
  requirements.txt       Flask and timezone data versions
  .gitignore             Files Git should ignore
  README.md              Setup and learning notes
```

## Run on Windows

Open this folder in VS Code, then open a PowerShell terminal in it.
The environment and Flask are already installed in this workspace.

```powershell
.\.venv\Scripts\python.exe -m flask --app app run --debug --host 127.0.0.1
```

Open http://127.0.0.1:5000 in your browser. Press Ctrl+C in the terminal to stop.
The server listens on your computer only. Debug mode reloads Python changes
while you develop; refresh your browser after editing HTML or CSS.

`-m flask` runs Flask using the selected Python interpreter. `--app app` tells
Flask to load `app.py`. `--debug` enables development diagnostics and reloading.

In VS Code, use **Python: Select Interpreter** from the Command Palette
(Ctrl+Shift+P) and select `.venv\Scripts\python.exe` if the Python extension
is installed. The terminal command above works without activating the environment.

For a fresh copy of the project, create the environment and install packages first:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`venv` creates an isolated Python environment. `pip` installs packages, and
`-r requirements.txt` tells it to read the package list from that file.

## How the homepage works

1. A browser requests `/`, the site's root URL.
2. `app = Flask(__name__)` creates the application. `__name__` helps Flask locate
   resources such as the templates and static folders.
3. `@app.route("/")` connects that URL to the `home()` Python function.
4. `render_template("index.html")` loads the HTML template and returns the page.
5. The template uses `url_for` to produce the CSS file's URL. The browser requests
   that stylesheet and applies its appearance rules.

HTML describes content, CSS describes appearance, and Python handles the request.

## Increment 1 exercise (completed)

Change “Small steps, steady growth.” in `templates/index.html` to a phrase that
motivates you. Refresh the browser and check that your phrase appears.

Then explain in your own words: which Python function runs when you visit `/`?

## Increment 2: save a completed activity

On the homepage, click **Record a completed activity**, or visit
http://127.0.0.1:5000/activities/new directly.

All six fields are required. Duration is a whole number from 1 to 1,440 minutes
(one day). Dates may be today or earlier, using Africa/Dar_es_Salaam time.
The `tzdata` package supplies timezone information on Windows.

### Follow one submission

1. **GET** `/activities/new` runs `new_activity()` and displays the empty form.
2. Clicking **Save completed activity** sends a **POST** request to the same URL.
3. `request.form` contains the submitted values, identified by each HTML field's
   `name` attribute. They arrive as text, even the duration.
4. `validate_activity()` checks them. Invalid submissions show messages and retain
   the entered values. Browser checks help too, but Python checks remain necessary.
5. `save_activity()` in `database.py` inserts one row into the `activities` table.
   A table groups related records; a row represents one completed activity.
6. `connection.commit()` saves the change in `instance/growthlog.sqlite3`.
   The `?` SQL placeholders pass values separately from the SQL instructions.
7. Flask redirects to a confirmation URL. `get_activity()` reads that saved row
   back from SQLite. Refreshing this page reads the row without inserting another.

Start by reading `new_activity()` in `app.py`. Then follow its call to
`save_activity()` in `database.py`. You do not need to memorize every line.

The database is created automatically when first used. Keep its file to retain
your entries between app runs. It is ignored by Git, along with `.venv`.
The confirmation URL and journal can be revisited after a restart.

### Increment 2 exercise

Record one real activity with a short reflection. On its confirmation page,
refresh and check that the saved details still appear. Stop the server with
Ctrl+C, run it again, and refresh that same URL to see persistence in action.

Then answer: does clicking **Save completed activity** send a GET or a POST request?

Pause here before the next increment.

### Run the checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`unittest` is Python's built-in testing tool. `discover -s tests` finds checks in
the `tests` folder, and `-v` prints each result. These checks use a temporary
database and do not write sample records to your personal database.

## Increment 3: view your journal

Click **View your journal** on the homepage or confirmation page, or open
http://127.0.0.1:5000/journal. The journal shows all six fields for each completed
activity. It shows an invitation to record your first activity if there are none.

### Follow a journal request

1. The browser sends **GET** `/journal`.
2. Flask runs `journal()` in `app.py`.
3. That function calls `list_activities()` in `database.py`.
4. `SELECT * FROM activities` reads the saved rows. `ORDER BY activity_date DESC,
   id DESC` sorts newest activity dates first, then most recently saved first
   within each date. Our dates use the sortable `YYYY-MM-DD` format.
5. `.fetchall()` returns a list of rows. Compare this with `.fetchone()` in
   `get_activity()`, which reads just one row.
6. `render_template("journal.html", activities=activities)` passes that list
   to the template under the name `activities`.
7. `{% for activity in activities %}` repeats the HTML section once per row.
   `{{ activity.title }}` inserts the current row's title. The loop's `{% else %}`
   section appears only when the list is empty.

The template instructions are Jinja syntax, processed by Flask before the browser
receives the HTML. This page does not need JavaScript.

### Increment 3 exercise

Open your journal and find the activity you saved earlier. If you have another
completed activity to record, add it and check that both appear in date order.

In `templates/journal.html`, find `{{ activity.title }}`. Which field name would
you use instead of `title` to display the activity's category?

Pause here before adding editing and deleting.

## Increment 4: edit an activity

Open the journal and click **Edit activity** on an entry. The form starts with
its saved values. Change a field and click **Save changes**. The confirmation
shows the updated record; **View your journal** returns to the list.
**Cancel and return to journal** leaves without saving your form changes.

### Follow an edit

1. Each activity has an integer `id` that identifies its database row.
2. A link like `/activities/3/edit` sends a GET request. Flask passes `3` to
   `edit_activity(activity_id)` through the route's `<int:activity_id>` part.
3. `get_activity()` reads that row. A missing ID returns 404 (not found).
4. `dict(activity)` turns the row into a dictionary of field names and values.
   `form.pop("id")` removes the ID from the editable fields; the URL identifies
   which record to update.
5. Both new and edit routes render `activity_form.html`. They pass `form_title`,
   `form_action`, and `submit_label` to give the shared form the appropriate
   heading, submission URL, and button text.
6. Saving sends POST to the edit URL. `validate_activity()` applies the same
   rules used for new entries. Invalid input stays in the form for correction;
   the previous saved record is kept until a valid submission succeeds.
7. `update_activity()` uses SQL `UPDATE ... SET ... WHERE id = ?` to change
   that row, then commits. Its ID stays the same and no extra row is created.
8. Flask redirects to the existing confirmation page, reading back the changes.
   The journal also reads saved rows each time, so an edited date changes the
   entry's position in the list.

`INSERT` adds a row. `UPDATE` changes a row. The `WHERE id = ?` clause selects
the row to change; without a WHERE clause, an UPDATE would affect every row.
The `?` placeholders keep submitted values separate from the SQL command.

### Increment 4 exercise

Edit one saved activity and add a sentence to its reflection. Save, return to the
journal, and check that the sentence appears on the same entry. Try editing it
again, but use **Cancel and return to journal** to leave without saving.

Then explain: what does `WHERE id = ?` prevent our UPDATE command from doing?

Pause here before adding deletion or weekly progress.

## Increment 5: delete an activity

In the journal, click **Delete activity**. Check the activity details on the
confirmation page. **Cancel and keep activity** returns to the journal without
changing the record. **Yes, delete this activity** permanently removes it and
returns to the journal. There is no undo for deletion.

### Follow a deletion

1. The journal link sends GET to `/activities/<id>/delete`.
2. `confirm_delete_activity()` reads that activity and renders the confirmation.
   Viewing, refreshing, or leaving this page does not delete anything.
3. The confirmation button submits a POST request to the same URL.
4. Flask checks the confirmation token and the activity ID before proceeding.
5. `delete_activity()` runs `DELETE FROM activities WHERE id = ?`, then commits.
   The WHERE clause limits deletion to the selected row.
6. Flask redirects to `/journal`. Its fresh database query reflects the deletion.
   Refreshing the journal does not repeat the POST. A missing activity returns 404.

The hidden token ties the submission to the confirmation prepared for this
browser and activity. `session` stores the ID and token in a signed cookie;
Flask's secret key prevents someone from changing that cookie unnoticed.
This local app generates its key at startup. If you restart the server, or open
another delete confirmation, reopen the desired confirmation before submitting.
The token is consumed after a successful deletion.

### Increment 5 exercise

Create a disposable activity titled **Deletion practice**. Open its delete
confirmation and choose Cancel. Check that it is still in the journal. Then
open the confirmation again and confirm deletion. Check that only that entry
disappears.

Then answer: why does the Delete activity link use GET, while the final
confirmation button uses POST?

Pause here before building the weekly dashboard.

## Increment 6: your weekly dashboard

Open http://127.0.0.1:5000/ to see the current Monday-Sunday week, progress toward
five growth days, and an overview of the seven dates. The timezone is
Africa/Dar_es_Salaam. A day counts when it has at least one saved completed
activity with a non-whitespace reflection. Fitness counts just like other categories.

Multiple activities on the same date contribute one day. All records in this
milestone represent completed activities; planned tasks are a later feature.
Future dates cannot be submitted through the form and are also excluded from
the dashboard's count. A day without an entry is neutral; rest is encouraged.

### Follow the calculation

1. `home()` calls `local_today()` to get today's date in Dar es Salaam.
2. `today.weekday()` returns 0 for Monday through 6 for Sunday. Subtracting
   that many days with `timedelta` gives this week's Monday. Adding six gives Sunday.
3. `get_growth_dates()` queries saved records between Monday and today, inclusively.
4. It uses `.strip()` to check that each reflection contains more than whitespace.
5. The `{...}` set comprehension collects unique date strings. For example,
   `{"2026-09-28", "2026-09-28", "2026-09-29"}` contains two dates, not three.
6. `len(growth_dates)` is the number of growth days. The template displays that
   count and marks each qualifying date in the seven-day overview.
7. `min(growth_days, WEEKLY_GOAL)` caps the progress bar at five. The text still
   shows the actual total when six or seven dates qualify.

There is no stored progress counter to keep synchronized. Each visit or refresh
reads saved records again, so changing dates or deleting entries recalculates the
result. Deleting one of two activities on a date keeps that day; deleting its
last qualifying activity removes it from the count. A page left open needs a
refresh to show changes or a new week.

### Increment 6 exercise

Open the dashboard and compare its marked dates with your journal. Pick a date
with two completed activities, if you have one, and notice that it contributes
only one day. You can also reason about this example without adding sample data:

You record reading and fitness on Monday, and coding on Wednesday, all with
reflections. How many growth days should the dashboard show?

Pause here. Milestone 1 is complete; do not start later milestones yet.

## Agreed milestone 1 scope

- Dashboard showing progress toward five distinct days in a Monday–Sunday week.
- Completed activity form: date, title, category, duration in minutes, what I did,
  and what I learned or improved.
- Journal with viewing, editing, and deleting; persistent SQLite storage.
- A day qualifies when it has a completed activity with a reflection. Fitness counts.
- Reject future dates for completed activities; use Africa/Dar_es_Salaam initially.
- Derive progress from saved records, including after edits and deletions.
- Distinguish completed activities from planned tasks; planning features come later.
- Encourage consistency without penalizing rest days.

Later milestones only: habits, to-do lists, schedules, recurring activities,
reminders, fitness details, weekly reflections, user accounts, and hosting.
