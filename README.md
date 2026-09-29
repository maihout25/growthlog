# GrowthLog

A personal growth journal and planner built with Python, Flask, SQLite, HTML,
CSS, and plain JavaScript. Aim for intentional growth on five different days
per week, with room for rest.

## What is included

- Weekly dashboard: distinct completed dates, Monday-Sunday, Africa/Dar_es_Salaam.
- Completed activity journal with reflections, editing, and confirmed deletion.
- Planned tasks and to-do list, with optional dates, times, and reminders.
- Recurring habits on your chosen weekdays, with a weekly schedule and archive.
- Task/habit completion creates one journal entry; repeated submissions reuse it.
- Optional fitness details: exercise, sets, reps, weight, distance, and notes.
- Editable weekly reflections with summaries from saved activities.
- Local accounts, hashed passwords, separate user records, and protected forms.
- In-app reminders plus optional browser notifications while the app is open.

## Run on Windows

From the project folder in VS Code's PowerShell terminal:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m flask --app app run --debug --host 127.0.0.1
```

The first two commands are needed only for initial setup or dependency changes.
Open http://127.0.0.1:5000 and create your first local account. Stop with Ctrl+C.

Upgrading from milestone 1 preserves your journal. On first database access, the
app saves a backup in `instance/backups/` and adds the new tables and ownership
column. Your first account claims existing activities. Subsequent accounts
start with their own empty journal. No account is created for you automatically.

Passwords must contain at least 10 characters. Change yours on the account page.
This local version does not send email or provide email password recovery.

## Work online with GitHub Codespaces

The repository includes `.devcontainer/devcontainer.json`. Once uploaded to
GitHub, use **Code > Codespaces > Create codespace on main**. Container setup
installs the dependencies into `.venv` automatically.

In the Codespaces terminal, run:

```bash
.venv/bin/python -m flask --app app run --host 127.0.0.1 --reload
```

Open port 5000 from the **Ports** tab, keeping its visibility **Private**.
Create a GrowthLog account in this new environment. Codespaces is a development
workspace; its preview is available while the Codespace and app are running.
See [GitHub's Codespaces guide](https://docs.github.com/en/codespaces/quickstart).

Code syncs through Git commits and pushes. Your SQLite records do not sync via
GitHub: `instance/` and database files are ignored. Keep a separate backup before
deleting a Codespace if you used it for real journal entries.

## A short tour

1. **Dashboard** shows growth days from completed journal entries.
2. **Plans & habits** lets you add intentions. A future plan needs no reflection.
3. **Schedule** shows tasks and recurring habit occurrences by week. Use
   **Record completion** after doing one, filling in the actual date, duration,
   what you did, and what you learned.
4. **Journal** shows completed records. A Fitness entry has a fitness-details link.
5. **Reflections** lets you look back at this week or a past week.
6. Your username opens **Account**, where you can change your password.

Adding plans or habits never increases the growth count. Only completed dates
with a nonblank reflection qualify. Fitness counts. Completed future dates are
rejected. Edits/deletions recalculate progress on your next page load.

Deleting a completed activity returns its linked task to pending and removes
its linked habit completion and optional fitness details. Deleting a plan keeps
its completed journal entry. Archiving a habit stops uncompleted occurrences and
reminders; existing journal entries remain. Changing a Fitness category preserves
its optional measurements, available again if you change it back to Fitness.

## Reminders

Choose a scheduled time and reminder lead time on a task or habit. The browser
checks every minute while GrowthLog is open and the server is running. Reminders
cover scheduled items today and advance reminders for tomorrow; old missed
reminders are not accumulated. Dismissals are saved for your account.

Browser notifications are optional and require clicking the enable button and
your browser's permission. Availability depends on the browser and operating
system. In-app reminders work without that permission. Closed tabs, stopped
Codespaces, and stopped servers do not deliver reminders.

## Data and backups

- `instance/growthlog.sqlite3` contains accounts and personal records.
- `instance/secret_key` keeps login sessions signed across server restarts.
- Both are excluded from Git. Do not upload them to your code repository.
- To back up manually, stop the server and copy the `instance` folder to a private
  location. To restore, stop the server and restore that folder from your backup.
- `GROWTHLOG_SECRET_KEY` may supply a secret instead of the local key file.

## Test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

In Codespaces use `.venv/bin/python -m unittest discover -s tests -v`.
Checks use temporary databases, not your personal journal. They cover dates,
progress, accounts, migrations, ownership, planning, recurrence, reminders,
reflections, fitness, and deletion behavior.

## Learn the code

Read [WALKTHROUGH.md](WALKTHROUGH.md) for a guided tour. The original incremental
lessons are preserved in [docs/milestone-1-notes.md](docs/milestone-1-notes.md).

This version is intended for local use and private development previews. Public
hosting still needs a chosen provider, production serving/configuration,
persistent storage and backups, and a deployment-specific security review.
