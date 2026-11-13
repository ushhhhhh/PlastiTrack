"""
SQLite database setup for PlastiTrack.

* The database file lives in ``<project root>/database/plastitrack.db`` by
  default (override with the PLASTITRACK_DB environment variable or the
  ``DATABASE`` Flask config key - the tests use a temporary file).
* All tables are created automatically on start-up (CREATE TABLE IF NOT
  EXISTS), so no manual migration step is needed.
* The built-in challenge catalogue is inserted/updated on start-up.
"""

import os
import sqlite3

from flask import current_app, g

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "database", "plastitrack.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,          -- user identifier, e.g. 'riya_22'
    display_name  TEXT,
    is_sample     INTEGER NOT NULL DEFAULT 0, -- 1 = demo data, not a real person
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS footprints (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recorded_at      TEXT NOT NULL,           -- ISO 8601, UTC
    weekly_grams     REAL NOT NULL,
    annual_kg        REAL NOT NULL,
    annual_co2e_kg   REAL NOT NULL,
    eco_score        INTEGER NOT NULL,
    dataset_version  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_footprints_user_time
    ON footprints(user_id, recorded_at, id);

CREATE TABLE IF NOT EXISTS footprint_items (
    footprint_id     INTEGER NOT NULL REFERENCES footprints(id) ON DELETE CASCADE,
    item_id          TEXT NOT NULL,
    weekly_quantity  REAL NOT NULL,
    weekly_grams     REAL NOT NULL,
    PRIMARY KEY (footprint_id, item_id)
);

CREATE TABLE IF NOT EXISTS challenges (
    id             INTEGER PRIMARY KEY,
    slug           TEXT NOT NULL UNIQUE,
    title          TEXT NOT NULL,
    description    TEXT NOT NULL,
    related_item   TEXT,                    -- item id from the dataset
    duration_days  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS user_challenges (
    user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    challenge_id  INTEGER NOT NULL REFERENCES challenges(id),
    status        TEXT NOT NULL CHECK (status IN ('joined', 'completed')),
    joined_at     TEXT NOT NULL,
    completed_at  TEXT,
    PRIMARY KEY (user_id, challenge_id)
);

CREATE TABLE IF NOT EXISTS teams (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description  TEXT,
    is_sample    INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

-- One team per user. joined_at is the participation record.
CREATE TABLE IF NOT EXISTS team_members (
    user_id    TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    team_id    INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    joined_at  TEXT NOT NULL
);
"""

# Built-in challenge catalogue. These are real, usable challenges (not
# sample data). Completing one is a SELF-REPORTED action.
CHALLENGES = [
    (1, "no-plastic-bottles-7-days",
     "Avoid plastic water bottles for seven days",
     "Carry a refillable steel or copper bottle and do not buy any bottled "
     "water for a full week.", "bottle", 7),
    (2, "reusable-shopping-bag",
     "Carry a reusable shopping bag",
     "Keep a cloth or jute bag with you and refuse plastic carry bags for "
     "seven days.", "bag", 7),
    (3, "no-disposable-cutlery",
     "Avoid disposable cutlery",
     "Use your own spoon/fork set instead of disposable cutlery for seven "
     "days.", "cutlery", 7),
    (4, "reusable-containers",
     "Use reusable containers",
     "Take food away only in your own tiffin or container for seven days.",
     "box", 7),
    (5, "no-single-use-cups",
     "Avoid single-use plastic cups",
     "Use your own mug, glass or a kulhad at the canteen and tea stall for "
     "seven days.", "cup", 7),
]


def get_db_path(app=None):
    app = app or current_app
    return (app.config.get("DATABASE")
            or os.environ.get("PLASTITRACK_DB")
            or DEFAULT_DB_PATH)


REQUIRED_TABLES = {"users", "footprints", "footprint_items", "challenges",
                   "user_challenges", "teams", "team_members"}


def connect(path):
    # timeout: wait up to 10 s for another writer instead of failing with
    # "database is locked" when several requests write at the same time.
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    """Return the SQLite connection for the current request."""
    if "db" not in g:
        g.db = connect(get_db_path())
    return g.db


def close_db(_exc=None):
    """Close the request's connection. Anything not committed (e.g. because
    the request failed half-way) is rolled back explicitly, so a failed
    request can never leave partial data behind."""
    db = g.pop("db", None)
    if db is not None:
        if db.in_transaction:
            db.rollback()
        db.close()


def init_db(path):
    """Create the database file, tables and challenge catalogue."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            """INSERT INTO challenges
                   (id, slug, title, description, related_item, duration_days)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   slug = excluded.slug, title = excluded.title,
                   description = excluded.description,
                   related_item = excluded.related_item,
                   duration_days = excluded.duration_days""",
            CHALLENGES,
        )
        conn.commit()
    finally:
        conn.close()


def init_app(app):
    init_db(get_db_path(app))
    app.teardown_appcontext(close_db)
