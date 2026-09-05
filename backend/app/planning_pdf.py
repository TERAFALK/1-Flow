"""Veckans planeringsmöte som PDF.

Ersätter Word-dokumentet som gicks igenom fysiskt med verkstaden varje vecka.
Samma avsnitt i samma ordning som originalet, men satt med Flows sidhuvud och
den nuvarande logotypen.

Bygger på ``sales_pdf._Doc`` – samma sidmotor som säljutskrifterna – men med
``table_wrapped`` i stället för ``table``: beskrivningskolumnen innehåller hela
meningar och Ansvar två fullständiga namn, och den vanliga tabellen klipper
varje cell till en rad.
"""
import io

from reportlab.lib.units import mm

from .sales_pdf import _Doc

WEEKDAYS = ["Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag", "Lördag", "Söndag"]

# A4 stående, 174 mm innehållsbredd
COL_CUSTOMER = 38 * mm
COL_DESCRIPTION = 96 * mm
COL_ASSIGNEE = 40 * mm


def _weekday(day) -> str:
    """"Måndag 1 sep" – datumet med, så att bladet går att läsa utan kalender."""
    if not day.day_date:
        return ""
    name = WEEKDAYS[day.day_date.weekday()]
    return f"{name} {day.day_date.day}/{day.day_date.month}"


def build_planning_pdf(meeting, items, absences=()) -> io.BytesIO:
    """``items`` är redan sorterade och kompletta med ansvariga och arbetsorder."""
    period = f"{meeting.monday_date.isoformat()} – {(meeting.days[-1].day_date.isoformat() if meeting.days else '')}"
    doc = _Doc(
        f"Planering vecka {meeting.iso_week}",
        period.strip(" –"),
        footer="Flow – Planeringsmöte",
    )

    # ── Veckoschemat ─────────────────────────────────────────────────────────
    schedule = [(_weekday(d), d.text or "") for d in meeting.days if (d.text or "").strip()]
    if schedule:
        doc.heading("Veckan")
        doc.table_wrapped(
            ["Dag", ""], [COL_CUSTOMER, COL_DESCRIPTION + COL_ASSIGNEE], schedule
        )

    # ── Pågående arbete ──────────────────────────────────────────────────────
    # Avbockade rader utelämnas: de stryks på papperet under mötet, och en rad
    # som redan är klar innan bladet skrivs ut är brus.
    open_items = [i for i in items if not i.done]
    doc.heading("Pågående arbete / ej startat arbete")
    doc.table_wrapped(
        ["Kund", "Beskrivning arbete", "Ansvar"],
        [COL_CUSTOMER, COL_DESCRIPTION, COL_ASSIGNEE],
        [
            (
                (item.customer.name if item.customer else item.customer_text) or "",
                item.description or "",
                "\n".join(a.user.full_name for a in item.assignees if a.user),
            )
            for item in open_items
        ],
    )

    # ── Fritextavsnitten ─────────────────────────────────────────────────────
    if absences:
        doc.heading("Frånvaro denna vecka")
        doc.table_wrapped(
            ["Person", "Period", "Typ"],
            [COL_CUSTOMER + 20 * mm, COL_DESCRIPTION - 20 * mm, COL_ASSIGNEE],
            [
                (
                    a.user.full_name if a.user else "",
                    f"{a.start_date.isoformat()} – {a.end_date.isoformat()}",
                    (a.kind or "").capitalize(),
                )
                for a in absences
            ],
        )

    for heading, body in (
        ("Noteringar", meeting.notes),
        (meeting.ffb_heading or "Aktuellt FFB", meeting.ffb_current),
        (meeting.quotes_heading or "Pågående offerter", meeting.open_quotes),
        (meeting.future_heading or "Kommande arbete", meeting.future_work),
    ):
        if (body or "").strip():
            doc.heading(heading)
            doc.rich(body)

    return doc.finish()
