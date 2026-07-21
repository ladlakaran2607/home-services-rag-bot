# CRM integration: the adapter, the schema, and the GoHighLevel mapping

## The pattern: choose the backend last

The bot writes to a two-method CRM interface. Everything above the interface
(the booking node, the graph, the frontend) is backend-agnostic; everything
below it is swappable. Active backend is selected by environment: if
DATABASE_URL is set, Postgres; otherwise an in-memory mock for tests.

| Adapter call | This repo (Postgres) | GoHighLevel equivalent |
|---|---|---|
| create_or_update_lead | INSERT ... ON CONFLICT (phone) DO UPDATE | POST /contacts/ (upsert) |
| book_appointment | INSERT appointments / extend services array | POST /calendars/events/appointments |
| service-area check | plain code against the city set | custom field validation / workflow |
| financing rules | knowledge base + retrieval | custom values / workflow conditions |

The last two rows are the interesting mapping: what GHL implements as
workflow configuration, this build implements as either deterministic code or
retrieved knowledge. Porting to a real GHL account is wiring the top two
calls and translating the bottom two into GHL's own primitives.

## Schema decisions (db/schema.sql)

- **Phone is the dedupe key** (UNIQUE on contacts.phone), matching how real
  CRMs identify returning customers. Upserting twice updates one record.
- **COALESCE merge on update**: a new non-null value wins, a missing value
  never erases what was known. Same rule the booking node applies in memory.
- **appointments.services is an array**, because "book that too" mid-visit
  must extend one truck roll, not schedule a second.
- **UNIQUE (contact_id, date)** is the idempotency guard promoted to physics:
  one visit per contact per day, unbypassable by any buggy caller. The guard
  existed first as Python in the adapter; moving it into the database is the
  general lesson (enforce at the lowest layer that can).
- **status** (booked / completed / cancelled) exists for the reschedule and
  history flows a real deployment adds next.

## Behavioral decisions

- **Capture eagerly, book lazily.** The contact is upserted the moment name
  and phone exist, mid-conversation, before any booking completes. A booking
  abandoned halfway is still a lead; the original design that only wrote on
  completed bookings would have dropped exactly the customers a nurture bot
  exists to keep. Booking fires only when all required fields are present.
- **No LLM tool-calling.** The mini model extracts structured fields from
  the conversation (with today's date injected so "next Tuesday" becomes a
  real date); plain code checks completeness and calls the adapter. The model
  cannot book without a phone number, cannot invent a date, cannot call the
  wrong tool, because it never calls anything.

## The GUI layer: NocoDB over the same tables

NocoDB (open source, one container in docker-compose) connects to the same
Postgres as an external data source and renders contacts and appointments as
spreadsheet grids: the demo-visible CRM without a SaaS dependency. Setup
notes that cost an hour of debugging so you do not repeat them:

- NocoDB connects from inside the Docker network: host is the compose
  service name (postgres), port 5432, not localhost:5433.
- NocoDB ships an SSRF guard that blocks data sources on private addresses.
  NC_ALLOW_LOCAL_EXTERNAL_DBS=true in the compose environment enables it,
  deliberate and safe on a local lab.
- Keep Allow Schema Change off in NocoDB: db/schema.sql in git is the source
  of truth, and the GUI should be physically unable to drift it.

## Swapping backends

MockCRM (tests, offline), PostgresCRM (active), AirtableCRM or a real GHL
client (each an afternoon: implement the same two methods, keep the same
idempotency semantics). The decision memo covers when each backend is the
right choice; the point of this file is that the bot never has to know.
