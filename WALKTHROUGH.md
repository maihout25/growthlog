# Learning your finished local app

Start the app and keep these notes beside VS Code. Follow one small journey at a
time. You do not need to memorize every file.

## 1. Follow the original homepage

Open `app.py` and find `home()`. The browser sends GET `/`. Flask finds Monday,
reads qualifying dates from SQLite, counts the set with `len()`, and passes the
result to `templates/index.html`.

Exercise: two activities on Tuesday and one on Thursday still mean two growth
days. Find the line that ensures duplicate dates are counted once.

## 2. Understand the new files

| File | Responsibility |
| --- | --- |
| `app.py` | Dashboard and completed activity routes |
| `auth.py` | Accounts, sessions, password hashing, and form protection |
| `planner.py` | Tasks, recurring habits, schedule, and reminder routes |
| `insights.py` | Optional fitness details and weekly reflections |
| `database.py` | Database connections, upgrades, and activity queries |
| `schema.sql` | Tables and relationships between records |
| `configuration.py` | A persistent secret for signed login cookies |
| `templates/base.html` | Shared navigation and page layout |
| `static/style.css` | Appearance and small-screen layouts |
| `static/reminders.js` | Checks for due reminders without reloading the page |

A Flask **Blueprint** groups related routes. The final lines in `app.py` register
the account, planner, and insights blueprints with the application.

## 3. Follow a planned task

Open **Plans & habits**, then **Add a task**. Saving it sends POST to `new_task()`
in `planner.py`. It inserts a row into `planned_tasks`, not `activities`.

Later, **Record completion** collects what actually happened and the reflection.
`complete_task()` validates these values, inserts an activity, and saves that
activity's ID on the task. These two changes happen in one database transaction:
they either both succeed or neither is saved.

Before inserting, the route checks whether the task already has an `activity_id`.
Submitting again opens the existing entry. This is called **idempotence**: doing
the same operation again does not create an additional result.

Exercise: find the `if task["activity_id"]` check. Where does it redirect?

## 4. Follow a recurring habit

A habit stores weekdays such as `0,2,4` for Monday, Wednesday, Friday. The schedule
calculates occurrences for only the week you are viewing. It does not fill the
database with years of future entries.

When an occurrence is completed, `habit_completions` links the habit and planned
date to the actual journal entry. `UNIQUE(habit_id, occurrence_date)` prevents
two completion links for the same occurrence. The actual activity date determines
growth progress, even if you did the activity later than planned.

Exercise: find `habit_occurs()`. Which conditions stop an occurrence appearing?

## 5. Understand record ownership

After sign-in, the session contains your user ID. On each request, `auth.py` loads
the matching account into `g.user`, which exists for that request. Queries include
`user_id` so another account cannot read or change your entries by guessing a URL.

Passwords are checked against hashes. The database does not store the original
password. The browser's signed session cookie identifies its login.

CSRF tokens tie submitted forms to the browser session. A hidden field sends the
token with ordinary forms; reminder JavaScript sends it in a request header.

Exercise: find a hidden `csrf_token` field and its check in `auth.py`.

## 6. Understand database relationships

Foreign keys link records. Every connection enables `PRAGMA foreign_keys = ON`.
For example, a plan points to its completed activity. `ON DELETE SET NULL` clears
that link if you delete the activity, making the task pending again. Fitness
details use `ON DELETE CASCADE`, so deleting the activity removes its details too.

The upgrade preserves milestone 1 rows, adds ownership, and backs up the old
database first. The first account claims the old rows in one transaction.

Exercise: find the difference between SET NULL and CASCADE in `schema.sql`.

## 7. Follow a JavaScript reminder

`reminders.js` calls `fetch('/api/reminders')`. Flask returns **JSON**, a structured
list of currently due reminders. JavaScript creates visible links and buttons
from that data. Every minute it checks again. It uses `textContent` to display
user text safely instead of treating that text as HTML.

The app does not run a background notification service. The page and server must
be open. Browser notification permission is requested only after your click.

Exercise: find `setInterval`. How many milliseconds are in one minute?

## 8. Use Git when working online

Git records snapshots of code. A **commit** names a snapshot; **push** copies your
commits to GitHub; **pull** brings down newer commits. A **branch** lets you work
on a change separately before combining it with the main version.

The database and secret key are deliberately excluded. GitHub stores the app's
source code, while each local or Codespaces environment keeps its own data.

Try a small branch: change one heading, run the tests, commit, then push. Review
your diff first so you understand exactly what your commit contains.
