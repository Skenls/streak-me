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

CREATE INDEX IF NOT EXISTS claimed_invites_claimed_at_idx ON claimed_invites (claimed_at);

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS invite_code text;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS legacy_invites_revoked boolean NOT NULL DEFAULT false;
CREATE UNIQUE INDEX IF NOT EXISTS profiles_invite_code_idx ON profiles (invite_code)
    WHERE invite_code IS NOT NULL;

ALTER TABLE streaks ADD COLUMN IF NOT EXISTS restore_month date;
ALTER TABLE streaks ADD COLUMN IF NOT EXISTS restore_count smallint NOT NULL DEFAULT 0 CHECK (restore_count BETWEEN 0 AND 5);
CREATE INDEX IF NOT EXISTS streaks_completed_day_idx ON streaks (completed_day);

CREATE TABLE IF NOT EXISTS inline_pairs (
    chat_instance text PRIMARY KEY,
    streak_id bigint NOT NULL REFERENCES streaks (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS inline_pairs_streak_idx ON inline_pairs (streak_id);

CREATE TABLE IF NOT EXISTS streak_reminders (
    day date NOT NULL,
    user_id bigint NOT NULL REFERENCES profiles (id),
    PRIMARY KEY (day, user_id)
);
