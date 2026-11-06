-- ===== Matches =====
CREATE TABLE IF NOT EXISTS matches (
    id           BIGINT PRIMARY KEY,
    home_team    TEXT NOT NULL,
    away_team    TEXT NOT NULL,
    competition  TEXT NOT NULL,
    season       TEXT NOT NULL,
    match_date   DATE NOT NULL,
    home_score   INTEGER NOT NULL CHECK (home_score >= 0),
    away_score   INTEGER NOT NULL CHECK (away_score >= 0),
    data_source  TEXT NOT NULL CHECK (data_source IN ('statsbomb'))
);

-- ===== Match events: the fast feed, served through an index =====
-- StatsBomb minutes overlap between periods, so clock_seconds gives the true order.
CREATE TABLE IF NOT EXISTS match_events (
    id             BIGSERIAL PRIMARY KEY,
    match_id       BIGINT NOT NULL REFERENCES matches (id),
    period         INTEGER NOT NULL CHECK (period BETWEEN 1 AND 5),
    minute         INTEGER NOT NULL CHECK (minute BETWEEN 0 AND 150),
    second         INTEGER NOT NULL CHECK (second BETWEEN 0 AND 59),
    clock_seconds  INTEGER NOT NULL CHECK (clock_seconds >= 0),
    event_type     TEXT NOT NULL,
    team           TEXT,
    description    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS match_events_feed_idx
    ON match_events (match_id, clock_seconds, period, id);

-- ===== Fan reactions: generated data behind the deliberately slow query =====
-- These are not real. minute counts minutes played since kick-off.
-- There is deliberately no index beyond the primary key.
CREATE TABLE IF NOT EXISTS fan_reactions (
    id             BIGSERIAL PRIMARY KEY,
    match_id       BIGINT NOT NULL REFERENCES matches (id),
    minute         INTEGER NOT NULL CHECK (minute >= 0),
    fan_id         INTEGER NOT NULL,
    reaction_type  TEXT NOT NULL CHECK (reaction_type IN ('cheer', 'groan', 'gasp'))
);
