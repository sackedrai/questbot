"""Схема базы и список миграций."""

from __future__ import annotations


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id         INTEGER PRIMARY KEY,
    username      TEXT    DEFAULT '',
    display_name  TEXT    DEFAULT '',
    nickname      TEXT    DEFAULT '',
    difficulty    TEXT    DEFAULT 'medium',
    points        INTEGER DEFAULT 0,
    streak        INTEGER DEFAULT 0,
    best_streak   INTEGER DEFAULT 0,
    quests_done   INTEGER DEFAULT 0,
    correct       INTEGER DEFAULT 0,
    wrong         INTEGER DEFAULT 0,
    last_quest_day TEXT   DEFAULT '',
    created_at    REAL    DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id       INTEGER NOT NULL,
    day         TEXT    NOT NULL,
    game_type   TEXT    NOT NULL,
    difficulty  TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    points      INTEGER DEFAULT 0,
    status      TEXT    DEFAULT 'active',
    risky       INTEGER DEFAULT 0,
    started_at  REAL    DEFAULT 0,
    finished_at REAL    DEFAULT 0,
    item_key    TEXT    DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_quests_user_day ON quests (tg_id, day);
CREATE INDEX IF NOT EXISTS idx_quests_day       ON quests (day);
CREATE INDEX IF NOT EXISTS idx_quests_status    ON quests (status);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    kind        TEXT    DEFAULT 'quest',
    created_at  REAL    DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS achievements (
    tg_id     INTEGER NOT NULL,
    code      TEXT    NOT NULL,
    earned_at REAL    DEFAULT 0,
    PRIMARY KEY (tg_id, code)
);

CREATE TABLE IF NOT EXISTS pvp_matches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    UNIQUE,
    player1     INTEGER NOT NULL,
    player2     INTEGER DEFAULT 0,
    game_type   TEXT    DEFAULT '',
    difficulty  TEXT    DEFAULT '',
    payload     TEXT    DEFAULT '{}',
    status      TEXT    DEFAULT 'waiting',
    points1     INTEGER DEFAULT 0,
    points2     INTEGER DEFAULT 0,
    winner      INTEGER DEFAULT 0,
    created_at  REAL    DEFAULT 0,
    finished_at REAL    DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages (chat_id, id);
CREATE INDEX IF NOT EXISTS idx_pvp_players ON pvp_matches (player1, player2);

CREATE TABLE IF NOT EXISTS user_questions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id       INTEGER NOT NULL,
    question    TEXT    NOT NULL,
    answer      TEXT    NOT NULL,
    options     TEXT    DEFAULT '[]',
    category    TEXT    DEFAULT '',
    difficulty  TEXT    DEFAULT 'easy',
    status      TEXT    DEFAULT 'pending',
    created_at  REAL    DEFAULT 0,
    approved_at REAL    DEFAULT 0,
    approved_by INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_user_questions_tg_id ON user_questions (tg_id);
CREATE INDEX IF NOT EXISTS idx_user_questions_status ON user_questions (status);
"""


MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "users": [
        ("tz_offset", "INTEGER DEFAULT 3"),
        ("notify", "INTEGER DEFAULT 1"),
        ("pvp_wins", "INTEGER DEFAULT 0"),
        ("pvp_losses", "INTEGER DEFAULT 0"),
        ("pvp_points", "INTEGER DEFAULT 0"),
        ("streak_free_day", "TEXT DEFAULT ''"),
        ("adaptive_locked", "INTEGER DEFAULT 0"),
        ("locked_difficulty", "TEXT DEFAULT 'easy'"),
    ],
    "quests": [
        ("pvp_id", "INTEGER DEFAULT 0"),
        ("item_key", "TEXT DEFAULT ''"),
    ],
}

