-- ===== Matches =====
CREATE TABLE IF NOT EXISTS matches (
    id           BIGINT PRIMARY KEY,
    home_team    TEXT NOT NULL,
    away_team    TEXT NOT NULL,
    competition  TEXT NOT NULL,
    kickoff_at   TIMESTAMPTZ NOT NULL,
    data_source  TEXT NOT NULL CHECK (data_source IN ('placeholder', 'statsbomb'))
);

-- ===== Match events: the fast feed, served through an index =====
CREATE TABLE IF NOT EXISTS match_events (
    id           BIGSERIAL PRIMARY KEY,
    match_id     BIGINT NOT NULL REFERENCES matches (id),
    minute       INTEGER NOT NULL CHECK (minute BETWEEN 0 AND 150),
    second       INTEGER NOT NULL CHECK (second BETWEEN 0 AND 59),
    event_type   TEXT NOT NULL,
    team         TEXT,
    description  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS match_events_feed_idx
    ON match_events (match_id, minute, second, id);

-- ===== Fan reactions: generated data behind the deliberately slow query =====
-- There is deliberately no index beyond the primary key.
CREATE TABLE IF NOT EXISTS fan_reactions (
    id             BIGSERIAL PRIMARY KEY,
    match_id       BIGINT NOT NULL REFERENCES matches (id),
    minute         INTEGER NOT NULL CHECK (minute BETWEEN 0 AND 150),
    fan_id         INTEGER NOT NULL,
    reaction_type  TEXT NOT NULL CHECK (reaction_type IN ('cheer', 'groan', 'gasp'))
);
