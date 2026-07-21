-- Summit CRM schema. Applied automatically on the postgres container's
-- first boot (docker-entrypoint-initdb.d). To rebuild from scratch:
--   docker compose down -v && docker compose up -d

CREATE TABLE contacts (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    phone       TEXT NOT NULL UNIQUE,  -- the dedupe key, like every real CRM
    city        TEXT,
    service_line TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE appointments (
    id          SERIAL PRIMARY KEY,
    contact_id  INTEGER NOT NULL REFERENCES contacts(id),
    services    TEXT[] NOT NULL,       -- the "book that too" upgrade: one visit, many services
    date        DATE NOT NULL,
    time_window TEXT NOT NULL DEFAULT 'morning',
    status      TEXT NOT NULL DEFAULT 'booked',  -- booked | completed | cancelled
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- The idempotency guard, now enforced by the database itself:
    -- one visit per contact per day, no second truck, ever.
    CONSTRAINT one_visit_per_day UNIQUE (contact_id, date)
);
