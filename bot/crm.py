"""CRM adapter: one interface, swappable backends.

PostgresCRM is the system of record (summit_crm database from
docker-compose; NocoDB renders the same tables as the GUI). MockCRM
remains for tests and offline work. Selection is automatic: if
DATABASE_URL is set in .env, Postgres; otherwise the mock.

Every method maps 1:1 to a GoHighLevel API call (noted per method) so
the decision memo speaks the target gig's language.
"""

import os
from datetime import date as date_type

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from bot.state import Lead

load_dotenv()

# From company.md - the twelve served cities.
SERVICE_AREA = {
    "denver", "aurora", "lakewood", "arvada", "westminster", "thornton",
    "centennial", "littleton", "highlands ranch", "broomfield", "golden",
    "parker",
}


def in_service_area(city: str | None) -> bool:
    return bool(city) and city.strip().lower() in SERVICE_AREA


class PostgresCRM:
    """Real backend: plain SQL against the summit_crm database."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def _connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def create_or_update_lead(self, lead: Lead) -> int:
        # GHL equivalent: POST /contacts/ (upsert by phone)
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO contacts (name, phone, city, service_line)
                VALUES (%(name)s, %(phone)s, %(city)s, %(service_line)s)
                ON CONFLICT (phone) DO UPDATE SET
                    name = EXCLUDED.name,
                    city = COALESCE(EXCLUDED.city, contacts.city),
                    service_line = COALESCE(EXCLUDED.service_line, contacts.service_line)
                RETURNING id
                """,
                {
                    "name": lead.get("name"),
                    "phone": lead.get("phone"),
                    "city": lead.get("city"),
                    "service_line": lead.get("service_line"),
                },
            ).fetchone()
        print(f"   [crm] contact upserted (id={row['id']}) in Postgres")
        return row["id"]

    def book_appointment(self, lead_id: int, lead: Lead) -> dict:
        # GHL equivalent: POST /calendars/events/appointments
        visit_date = date_type.fromisoformat(lead["preferred_date"])
        service = lead.get("service_line")
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM appointments WHERE contact_id = %s AND date = %s",
                (lead_id, visit_date),
            ).fetchone()
            if existing:
                # One visit per day: extend the services list, never duplicate.
                services = list(existing["services"] or [])
                if service and service not in services:
                    services.append(service)
                conn.execute(
                    """
                    UPDATE appointments
                    SET services = %s,
                        time_window = COALESCE(%s, time_window)
                    WHERE id = %s
                    """,
                    (services, lead.get("time_window"), existing["id"]),
                )
                print(f"   [crm] appointment {existing['id']} extended: "
                      f"services={services} on {visit_date}")
                return {
                    "id": existing["id"],
                    "date": lead["preferred_date"],
                    "window": lead.get("time_window") or existing["time_window"],
                    "already_existed": True,
                }
            row = conn.execute(
                """
                INSERT INTO appointments (contact_id, services, date, time_window)
                VALUES (%s, %s, %s, %s)
                RETURNING id, time_window
                """,
                (lead_id, [service] if service else [], visit_date,
                 lead.get("time_window") or "morning"),
            ).fetchone()
        print(f"   [crm] appointment {row['id']} booked in Postgres: "
              f"{service} on {visit_date} ({row['time_window']})")
        return {
            "id": row["id"],
            "date": lead["preferred_date"],
            "window": row["time_window"],
        }


class MockCRM:
    """In-memory stand-in. Keys leads by phone number, like real CRMs."""

    def __init__(self) -> None:
        self.leads: dict[str, dict] = {}
        self.appointments: list[dict] = []

    def create_or_update_lead(self, lead: Lead) -> str:
        phone = lead["phone"]
        if phone not in self.leads:
            self.leads[phone] = {"id": f"L-{1000 + len(self.leads)}", **lead}
            print(f"   [crm] (mock) lead created {self.leads[phone]['id']}")
        else:
            self.leads[phone].update(lead)
            print(f"   [crm] (mock) lead updated {self.leads[phone]['id']}")
        return self.leads[phone]["id"]

    def book_appointment(self, lead_id: str, lead: Lead) -> dict:
        for existing in self.appointments:
            if existing["lead_id"] == lead_id and existing["date"] == lead.get("preferred_date"):
                existing["window"] = lead.get("time_window") or existing["window"]
                print(f"   [crm] (mock) appointment {existing['id']} reused")
                return {**existing, "already_existed": True}
        appointment = {
            "id": f"A-{2000 + len(self.appointments)}",
            "lead_id": lead_id,
            "service_line": lead.get("service_line"),
            "date": lead.get("preferred_date"),
            "window": lead.get("time_window") or "morning",
        }
        self.appointments.append(appointment)
        print(f"   [crm] (mock) appointment {appointment['id']} booked")
        return appointment


_dsn = os.getenv("DATABASE_URL")
crm = PostgresCRM(_dsn) if _dsn else MockCRM()
