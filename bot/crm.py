"""CRM adapter: one interface, swappable backends.

MockCRM stores in memory and prints what a real CRM would do - the P2
development backend. AirtableCRM (same methods, next step) is the real
one. Nothing outside this file knows which is active, and every method
maps 1:1 to a GoHighLevel API call (noted per method) so the decision
memo can speak the target gig's language.
"""

from bot.state import Lead

# From company.md - the twelve served cities.
SERVICE_AREA = {
    "denver", "aurora", "lakewood", "arvada", "westminster", "thornton",
    "centennial", "littleton", "highlands ranch", "broomfield", "golden",
    "parker",
}


def in_service_area(city: str | None) -> bool:
    return bool(city) and city.strip().lower() in SERVICE_AREA


class MockCRM:
    """In-memory stand-in. Keys leads by phone number, like real CRMs."""

    def __init__(self) -> None:
        self.leads: dict[str, dict] = {}
        self.appointments: list[dict] = []

    def create_or_update_lead(self, lead: Lead) -> str:
        # GHL equivalent: POST /contacts/ (upsert by phone)
        phone = lead["phone"]
        if phone not in self.leads:
            self.leads[phone] = {"id": f"L-{1000 + len(self.leads)}", **lead}
            print(f"   [crm] lead created {self.leads[phone]['id']}: "
                  f"{lead.get('name')} / {phone}")
        else:
            self.leads[phone].update(lead)
            print(f"   [crm] lead updated {self.leads[phone]['id']}")
        return self.leads[phone]["id"]

    def book_appointment(self, lead_id: str, lead: Lead) -> dict:
        # GHL equivalent: POST /calendars/events/appointments
        # Idempotency guard: one visit per lead per day. "Book that too"
        # mid-conversation must extend the existing visit, not send a
        # second truck.
        for existing in self.appointments:
            if existing["lead_id"] == lead_id and existing["date"] == lead.get("preferred_date"):
                existing["window"] = lead.get("time_window") or existing["window"]
                print(f"   [crm] appointment {existing['id']} already covers "
                      f"{existing['date']} - reusing, not duplicating")
                return {**existing, "already_existed": True}
        appointment = {
            "id": f"A-{2000 + len(self.appointments)}",
            "lead_id": lead_id,
            "service_line": lead.get("service_line"),
            "date": lead.get("preferred_date"),
            "window": lead.get("time_window") or "morning",
        }
        self.appointments.append(appointment)
        print(f"   [crm] appointment {appointment['id']} booked: "
              f"{appointment['service_line']} on {appointment['date']} "
              f"({appointment['window']})")
        return appointment


crm = MockCRM()
