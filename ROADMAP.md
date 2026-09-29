# GrowthLog: milestone status

The local app now includes completed activity tracking, planning, habits,
schedules, reminders, fitness details, weekly reflections, and separate accounts.
The original activity journal and five-day weekly progress rules remain intact.

Continue with Python, Flask, SQLite, HTML, CSS, and plain JavaScript. Keep the
app local on Windows. Preserve the user's records as the database grows.

## Implemented local features

1. **Planned tasks:** create and list intentions separately from completed
   activities, then edit, delete, and complete tasks through a reflection form.
2. **Habits and recurrence:** define repeated intentions, see due occurrences,
   and record actual completion without creating duplicate activities.
3. **Schedules and local reminders:** choose dates and times in Dar es Salaam,
   view upcoming plans, and show due reminders in the app. Clearly state when
   reminders require the app or browser to remain open.
4. **Fitness details and weekly reflections:** attach optional workout details
   to fitness activities and save one editable reflection for each week.
5. **Local accounts:** registration, login, logout, password hashing, form
   protection, and user-specific records. Explicitly assign existing personal
   records during setup rather than exposing them to every new account.

GitHub/Codespaces configuration is prepared for online development. Public hosting
remains a separate deployment step once a destination is chosen.

## Rules every milestone must preserve

- Weeks run Monday through Sunday in Africa/Dar_es_Salaam.
- Count distinct dates with completed activities and meaningful reflections.
- Fitness qualifies; plans and habit definitions alone do not.
- Completed dates cannot be in the future.
- Edits and deletions recalculate progress from the saved records.
- Rest days are neutral. Encourage consistency without penalties.
- Preserve data when adding tables or columns; test upgrades on a temporary copy.
- Completing a planned occurrence twice must not create duplicate activities.

## Teaching pace

The user chose to build the remaining local features together and walk through
the code afterward. See WALKTHROUGH.md for that guided explanation and exercises.
