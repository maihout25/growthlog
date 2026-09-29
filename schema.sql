CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY,
    activity_date TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes BETWEEN 1 AND 1440),
    what_i_did TEXT NOT NULL,
    reflection TEXT NOT NULL CHECK (length(trim(reflection)) > 0),
    user_id INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS planned_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    planned_date TEXT,
    planned_time TEXT,
    reminder_minutes INTEGER,
    activity_id INTEGER UNIQUE REFERENCES activities(id) ON DELETE SET NULL,
    cancelled INTEGER NOT NULL DEFAULT 0 CHECK (cancelled IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS habits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    weekdays TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT,
    planned_time TEXT,
    reminder_minutes INTEGER,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS habit_completions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
    occurrence_date TEXT NOT NULL,
    activity_id INTEGER NOT NULL UNIQUE REFERENCES activities(id) ON DELETE CASCADE,
    UNIQUE (habit_id, occurrence_date)
);

CREATE TABLE IF NOT EXISTS reminder_dismissals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    reminder_key TEXT NOT NULL,
    UNIQUE (user_id, reminder_key)
);

CREATE TABLE IF NOT EXISTS fitness_details (
    activity_id INTEGER PRIMARY KEY REFERENCES activities(id) ON DELETE CASCADE,
    exercise_type TEXT NOT NULL DEFAULT '',
    sets INTEGER,
    reps INTEGER,
    weight_kg REAL,
    distance_km REAL,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS weekly_reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    week_start TEXT NOT NULL,
    wins TEXT NOT NULL DEFAULT '',
    challenges TEXT NOT NULL DEFAULT '',
    next_week TEXT NOT NULL DEFAULT '',
    UNIQUE (user_id, week_start)
);
