CREATE TABLE IF NOT EXISTS profiles (
    id bigint PRIMARY KEY,
    name text NOT NULL,
    username text,
    photo_url text
);

CREATE TABLE IF NOT EXISTS streaks (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    low_id bigint NOT NULL REFERENCES profiles (id),
    high_id bigint NOT NULL REFERENCES profiles (id),
    low_day date,
    high_day date,
    completed_day date,
    days integer NOT NULL DEFAULT 0 CHECK (days >= 0),
    UNIQUE (low_id, high_id),
    CHECK (low_id < high_id)
);

CREATE INDEX IF NOT EXISTS streaks_high_id_idx ON streaks (high_id);

CREATE TABLE IF NOT EXISTS claimed_invites (
    token text PRIMARY KEY,
    receiver_id bigint NOT NULL REFERENCES profiles (id),
    claimed_at timestamptz NOT NULL DEFAULT now()
);
