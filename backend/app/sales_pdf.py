"""Utskrifter för Försäljning: en förfrågan eller en såld order på papper, med
allt som står på skärmen. Bygger på samma canvas-hjälpare som övriga PDF:er."""
import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas

from .models import SalesLeadKind
from .pdf_utils import draw_header, draw_info_panel, draw_paragraph, truncate
from .sales_common import lead_schedule, order_schedule

MARGIN = 18 * mm
PAGE_W, PAGE_H = A4
CONTENT_W = PAGE_W - 2 * MARGIN
MIN_Y = 22 * mm

STATUS_LABELS = {
    "ny": "Ny", "skickad": "Skickad", "jobbar": "Jobbar",
    "sald": "Såld", "avslutad": "Avslutad",
}
NOTE_LABELS = {"samtal": "Samtal", "mail": "Mail", "mote": "Möte", "anteckning": "Anteckning"}


def _d(value) -> str:
    return value.isoformat() if value else ""


def _money(value, currency) -> str:
    if value is None:
        return ""
    return f"{value:,.2f} {currency or 'EUR'}".replace(",", " ")


class _Doc:
    """Håller reda på y-läget och sköter sidbrytningar."""

    def __init__(self, title: str, subtitle: str):
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=A4)
        self.title = title
        self.subtitle = subtitle
        self.y = draw_header(self.c, PAGE_W, title, subtitle) - 6 * mm

    def new_page(self) -> float:
        self.c.showPage()
        self.y = draw_header(self.c, PAGE_W, self.title, self.subtitle) - 6 * mm
        return self.y

    def space(self, needed: float):
        """Bryter sidan om det som ska ritas inte får plats."""
        if self.y - needed < MIN_Y:
            self.new_page()

    def heading(self, text: str):
        self.space(14 * mm)
        self.y -= 4 * mm
        self.c.setFont("Helvetica-Bold", 10.5)
        self.c.setFillColor(colors.HexColor("#E2001A"))
        self.c.drawString(MARGIN, self.y, text.upper())
        self.y -= 3 * mm
        self.c.setStrokeColor(colors.HexColor("#e2e5e9"))
        self.c.setLineWidth(0.8)
        self.c.line(MARGIN, self.y, PAGE_W - MARGIN, self.y)
        self.y -= 5 * mm
        self.c.setFillColor(colors.black)

    def panels(self, left, right):
        """Två paneler sida vid sida. Returnerar den lägsta underkanten."""
        w = (CONTENT_W - 6 * mm) / 2
        rows = max(len([r for r in left[1] if r[1]]), len([r for r in right[1] if r[1]]))
        self.space(rows * 5 * mm + 16 * mm)
        y1 = draw_info_panel(self.c, MARGIN, self.y, w, left[0], left[1])
        y2 = draw_info_panel(self.c, MARGIN + w + 6 * mm, self.y, w, right[0], right[1])
        self.y = min(y1, y2) - 4 * mm

    def panel(self, title, rows):
        rows = [r for r in rows if r[1]]
        if not rows:
            return
        self.space(len(rows) * 5 * mm + 16 * mm)
        self.y = draw_info_panel(self.c, MARGIN, self.y, CONTENT_W, title, rows) - 4 * mm

    def table(self, headers, widths, rows):
        """Enkel tabell med automatisk sidbrytning."""
        if not rows:
            self.text("–")
            return

        def head():
            self.c.setFont("Helvetica-Bold", 8)
            self.c.setFillColor(colors.HexColor("#5a6675"))
            x = MARGIN
            for h, w in zip(headers, widths):
                self.c.drawString(x, self.y, h.upper())
                x += w
            self.y -= 2.5 * mm
            self.c.setStrokeColor(colors.HexColor("#c3ccd6"))
            self.c.setLineWidth(0.6)
            self.c.line(MARGIN, self.y, PAGE_W - MARGIN, self.y)
            self.y -= 4 * mm
            self.c.setFillColor(colors.black)

        self.space(20 * mm)
        head()
        for row in rows:
            if self.y < MIN_Y + 6 * mm:
                self.new_page()
                head()
            x = MARGIN
            self.c.setFont("Helvetica", 8.5)
            for cell, w in zip(row, widths):
                self.c.drawString(x, self.y, truncate(str(cell or ""), "Helvetica", 8.5, w - 3 * mm))
                x += w
            self.y -= 5 * mm

    def text(self, body: str):
        if not body:
            return
        self.space(10 * mm)
        self.y = draw_paragraph(
            self.c, body, MARGIN, self.y, CONTENT_W,
            min_y=MIN_Y, on_new_page=self.new_page,
        ) - 2 * mm

    def finish(self) -> io.BytesIO:
        self.c.setFont("Helvetica", 7.5)
        self.c.setFillColor(colors.HexColor("#9ba3ae"))
        self.c.drawRightString(PAGE_W - MARGIN, 12 * mm, "Flow – Försäljning")
        self.c.save()
        self.buf.seek(0)
        return self.buf


def _customer_rows(obj) -> list:
    """Kunduppgiftsblocket, identiskt på förfrågan och order."""
    cust = obj.customer
    contact = getattr(obj, "contact_person", None)
    if contact is None and getattr(obj, "lead", None) is not None:
        contact = obj.lead.contact_person
    return [
        ("Kund", cust.name if cust else ""),
        ("Org.nr", cust.org_number if cust else ""),
        ("Telefon", cust.phone if cust else ""),
        ("E-post", cust.email if cust else ""),
        ("Ort", cust.city if cust else ""),
        ("Kontaktperson", contact.name if contact else ""),
        ("Kontakt telefon", contact.phone if contact else ""),
        ("Kontakt e-post", contact.email if contact else ""),
    ]


def _schedule_rows(items) -> list:
    return [
        (
            i.name,
            _d(i.start_date),
            _d(i.end_date) if i.end_date != i.start_date else "",
            "Egen" if i.source == "custom" else "Auto",
        )
        for i in items
    ]


def _note_rows(notes) -> list:
    return [
        (_d(n.note_date), NOTE_LABELS.get(getattr(n.kind, "value", n.kind), ""), n.body)
        for n in sorted(notes, key=lambda n: (n.note_date, n.id), reverse=True)
    ]


def build_lead_pdf(lead) -> io.BytesIO:
    ffb = lead.kind == SalesLeadKind.feldbinder
    objekt = " ".join(x for x in [lead.product_type, lead.size] if x)
    doc = _Doc(
        "Offertförfrågan" if ffb else "Offert",
        f"{lead.customer.name if lead.customer else ''}"
        + (f" · {objekt}" if objekt else "")
        + (f" · Aktivitet {lead.activity_number}" if lead.activity_number else ""),
    )

    rows = [("Status", STATUS_LABELS.get(getattr(lead.status, "value", lead.status), ""))]
    if ffb:
        rows += [
            ("Aktivitetsnr", lead.activity_number),
            ("Objekt", objekt),
            ("Antal", lead.quantity if (lead.quantity or 0) > 1 else ""),
        ]
    rows += [
        ("Offertnummer", lead.quote_number),
        ("Uppskattat värde", _money(lead.estimated_value, lead.currency)),
        ("Ansvarig", lead.assignee.full_name if lead.assignee else ""),
        ("Nästa uppföljning", _d(lead.next_followup_date)),
        ("Avslutsorsak", lead.lost_reason),
        ("Arkiverad", _d(lead.archived_at.date() if lead.archived_at else None)),
    ]
    doc.panels(("Kund", _customer_rows(lead)), ("Förfrågan", rows))

    if lead.description:
        doc.heading("Beskrivning")
        doc.text(lead.description)

    steps = [("Förfrågan inkom", _d(lead.date_request))]
    if ffb:
        steps += [
            ("Skickad till FFB", _d(lead.date_sent_ffb)),
            ("Tillbaka från FFB", _d(lead.date_back_ffb)),
        ]
    steps.append(("Offert skickad till kund", _d(lead.date_sent_customer)))
    doc.heading("Tidslinje")
    doc.table(["Steg", "Datum"], [70 * mm, 40 * mm], steps)

    schedule = lead_schedule(lead)
    if schedule:
        doc.heading("Schema")
        doc.table(["Aktivitet", "Från", "Till", "Typ"],
                  [80 * mm, 30 * mm, 30 * mm, 20 * mm], _schedule_rows(schedule))

    if lead.notes:
        doc.heading("Interna anteckningar")
        doc.text(lead.notes)

    notes = _note_rows(lead.lead_notes)
    if notes:
        doc.heading("Uppföljning")
        doc.table(["Datum", "Typ", "Vad hände"], [24 * mm, 22 * mm, 128 * mm], notes)

    if lead.tasks:
        doc.heading("Uppgifter")
        doc.table(["", "Uppgift", "Ansvarig", "Klart till"],
                  [8 * mm, 92 * mm, 40 * mm, 28 * mm], _task_rows(lead.tasks))

    if lead.files:
        doc.heading("Filer")
        doc.table(["Fil", "Typ", "Uppladdad"], [100 * mm, 24 * mm, 36 * mm],
                  [(f.original_name,
                    "Bild" if (f.mime_type or "").startswith("image/") else "Dokument",
                    _d(f.uploaded_at.date() if f.uploaded_at else None))
                   for f in lead.files])

    return doc.finish()


def _task_rows(tasks) -> list:
    return [
        (
            "[x]" if t.completed else "[ ]",
            t.title + (f" – {t.description}" if t.description else ""),
            t.assigned_user.full_name if t.assigned_user else "",
            _d(t.due_date.date() if t.due_date else None),
        )
        for t in sorted(tasks, key=lambda t: (t.completed, t.id))
    ]


def build_lead_tasks_pdf(lead) -> io.BytesIO:
    """Bara uppgiftslistan, att ta med ut i verkstaden. Motsvarar arbetsorderns
    'Skriv ut lista'."""
    ffb = lead.kind == SalesLeadKind.feldbinder
    done = sum(1 for t in lead.tasks if t.completed)
    doc = _Doc(
        "Uppgifter",
        f"{'Offertförfrågan' if ffb else 'Offert'}"
        + (f" {lead.quote_number}" if lead.quote_number else f" #{lead.id}")
        + f" · {lead.customer.name if lead.customer else ''}"
        + f" · {done} av {len(lead.tasks)} klara",
    )
    if lead.description:
        doc.text(lead.description)
    doc.table(["", "Uppgift", "Ansvarig", "Klart till"],
              [8 * mm, 92 * mm, 40 * mm, 28 * mm], _task_rows(lead.tasks))
    return doc.finish()


def build_order_pdf(order) -> io.BytesIO:
    doc = _Doc(
        "Såld order",
        f"{order.order_number or 'Utan ordernummer'}"
        + f" · {order.customer.name if order.customer else ''}"
        + (f" · {order.product_type}" if order.product_type else "")
        + (" · ARKIVERAD" if order.archived_at else ""),
    )

    doc.panels(
        ("Kund", _customer_rows(order)),
        ("Order", [
            ("Ordernummer", order.order_number),
            ("Tillverkningsnr", order.serial_number),
            ("Typ", order.product_type),
            ("Pris", _money(order.price, order.currency)),
            ("Provision", _money(order.commission, order.currency)),
            ("Provision utbetald", _d(order.commission_paid_date)),
            ("Datum såld", _d(order.sold_date)),
            ("Planerad leverans", _d(order.planned_delivery)),
            ("Vecka", order.delivery_week),
            ("Levererad kund", _d(order.delivery_date)),
            ("Reg.nr", order.registration_number),
            ("Vikt", f"{order.weight_kg} kg" if order.weight_kg else ""),
            ("Besök hos FFB", "Ja" if order.visit_ffb else ""),
            ("Arkiverad", _d(order.archived_at.date() if order.archived_at else None)),
        ]),
    )

    active = [m for m in order.milestones if m.definition and m.definition.is_active]
    active.sort(key=lambda m: (m.definition.sort_order, m.definition.id))
    group = None
    for m in active:
        if m.definition.group_label != group:
            group = m.definition.group_label
            doc.heading(group)
            rows = []
            for x in active:
                if x.definition.group_label != group:
                    continue
                value = _d(x.value_date) or (x.value_text or "")
                rows.append((x.definition.label, value or "–"))
            doc.table(["Milstolpe", "Värde"], [90 * mm, 70 * mm], rows)

    if order.aocs:
        doc.heading("AOC")
        doc.table(
            ["AOC-nr", "Skickad kund", "Mailat FFB", "Kostnad EUR"],
            [40 * mm, 40 * mm, 40 * mm, 40 * mm],
            [
                (a.aoc_number or "–", _d(a.sent_customer), _d(a.mailed_ffb),
                 f"{a.cost_eur:.2f}" if a.cost_eur is not None else "")
                for a in sorted(order.aocs, key=lambda a: (a.sort_order or 0, a.id))
            ],
        )

    schedule = order_schedule(order)
    if schedule:
        doc.heading("Schema")
        doc.table(["Aktivitet", "Från", "Till", "Typ"],
                  [80 * mm, 30 * mm, 30 * mm, 20 * mm], _schedule_rows(schedule))

    if order.notes:
        doc.heading("Anteckningar")
        doc.text(order.notes)

    # Uppföljningen fortsätter på ordern, men förfrågans logg hör till historiken
    notes = list(order.order_notes) + (list(order.lead.lead_notes) if order.lead else [])
    rows = _note_rows(notes)
    if rows:
        doc.heading("Uppföljning")
        doc.table(["Datum", "Typ", "Vad hände"], [24 * mm, 22 * mm, 128 * mm], rows)

    if order.files:
        doc.heading("Filer")
        doc.table(["Fil", "Avsnitt"], [110 * mm, 50 * mm],
                  [(f.original_name, f.group_label or ("AOC" if f.aoc_id else "")) for f in order.files])

    return doc.finish()
