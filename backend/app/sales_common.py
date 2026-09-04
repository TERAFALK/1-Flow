"""Delat mellan sales_leads och sales_orders: kunduppgiftsblocket, egna
aktiviteter och uppbyggnaden av Gantt-schemat."""
from typing import List, Optional

from .models import SalesActivity, SalesLead, SalesLeadKind, SalesOrder
from .schemas import SalesActivityOut, SalesScheduleItem

# Färgerna följer avsnitten i ordervyn så att stapeln går att känna igen
GROUP_COLORS = {
    "Order & betalning":    "#2563eb",
    "Ritningar":            "#7c3aed",
    "Lackering":            "#d97706",
    "Registrering":         "#0891b2",
    "AOC":                  "#16a34a",
    "Fakturering":          "#dc2626",
    "Dokumentation":        "#64748b",
    "COA / framkomstintyg": "#be185d",
}
DEFAULT_COLOR = "#E2001A"


def contact_fields(customer, contact) -> dict:
    """Kunduppgifterna som både förfrågan och order visar. Kontaktpersonens
    uppgifter går före kundens, men kundens finns kvar som fallback."""
    return dict(
        customer_name=customer.name if customer else "",
        customer_phone=customer.phone if customer else None,
        customer_email=customer.email if customer else None,
        customer_org_number=customer.org_number if customer else None,
        contact_name=contact.name if contact else None,
        contact_phone=(contact.phone if contact else None) or (customer.phone if customer else None),
        contact_email=(contact.email if contact else None) or (customer.email if customer else None),
    )


def _join(*parts) -> Optional[str]:
    """Slår ihop delar till en rad och hoppar över de tomma."""
    joined = " ".join(str(p).strip() for p in parts if p and str(p).strip())
    return joined or None


def ffb_customer_block(customer, contact) -> dict:
    """Kundblocket på FFB-dokumenten, på engelska som mallarna.

    Lagras inte på posten utan slås upp varje gång dokumentet läses eller skrivs
    ut – rättar man en adress på kundkortet ska den slå igenom direkt i stället
    för att ligga kvar som en kopia från den dag posten skapades. Delas av
    beställningen och offertförfrågan.
    """
    return dict(
        vat_number=(customer.vat_number or customer.org_number) if customer else None,
        customer_number=customer.ffb_customer_number if customer else None,
        customer_name=customer.name if customer else None,
        address=customer.address if customer else None,
        postal_city=_join(customer.postal_code, customer.city) if customer else None,
        country=customer.country if customer else None,
        phone=(contact.phone if contact else None) or (customer.phone if customer else None),
        email=(contact.email if contact else None) or (customer.email if customer else None),
        contact_person=contact.name if contact else None,
    )


def activity_out(a: SalesActivity) -> SalesActivityOut:
    return SalesActivityOut(
        id=a.id, name=a.name, color=a.color,
        start_date=a.start_date, end_date=a.end_date, sort_order=a.sort_order,
    )


def _item(name: str, start, end=None, color: str = DEFAULT_COLOR) -> Optional[SalesScheduleItem]:
    """Hoppar över poster utan datum – ett tomt fält ska inte ge en tom rad."""
    if not start and not end:
        return None
    return SalesScheduleItem(
        name=name, color=color,
        start_date=start or end, end_date=end or start, source="auto",
    )


def lead_schedule(lead: SalesLead) -> List[SalesScheduleItem]:
    """Automatiska poster ur förfrågans datumfält, plus egna aktiviteter."""
    items = [_item("Förfrågan inkom", lead.date_request, color="#2563eb")]
    if lead.kind == SalesLeadKind.feldbinder:
        # Tiden hos FFB är den enda riktiga varaktigheten i förfrågan – resten är
        # händelser på en dag och ritas som endagsstaplar. Verkstadsofferter går
        # aldrig via FFB och har därför inte steget.
        items.append(_item("Hos FFB", lead.date_sent_ffb, lead.date_back_ffb, color="#7c3aed"))
    items += [
        _item("Offert till kund", lead.date_sent_customer, color="#16a34a"),
        _item("Uppföljning", lead.next_followup_date, color="#d97706"),
    ]
    return _finish(items, lead.activities)


def order_schedule(order: SalesOrder) -> List[SalesScheduleItem]:
    """Automatiska poster ur orderns fält, avbockade milstolpar och AOC-intyg."""
    items = [
        _item("Såld", order.sold_date, color="#16a34a"),
    ]

    for m in sorted(
        (m for m in order.milestones if m.definition and m.definition.is_active and m.value_date),
        key=lambda m: (m.definition.sort_order, m.definition.id),
    ):
        items.append(_item(
            m.definition.label, m.value_date,
            color=GROUP_COLORS.get(m.definition.group_label, DEFAULT_COLOR),
        ))

    for aoc in sorted(order.aocs, key=lambda a: (a.sort_order or 0, a.id)):
        label = f"AOC {aoc.aoc_number}" if aoc.aoc_number else "AOC"
        items.append(_item(label, aoc.sent_customer, aoc.mailed_ffb, color=GROUP_COLORS["AOC"]))

    items += [
        _item("Planerad leverans", order.planned_delivery, color="#0891b2"),
        _item("Levererad kund", order.delivery_date, color="#0891b2"),
        _item("Provision utbetald", order.commission_paid_date, color="#64748b"),
    ]
    return _finish(items, order.activities)


def _finish(auto_items, activities) -> List[SalesScheduleItem]:
    result = [i for i in auto_items if i]
    for a in sorted(activities, key=lambda a: (a.sort_order or 0, a.id)):
        result.append(SalesScheduleItem(
            name=a.name,
            color=a.color or DEFAULT_COLOR,
            start_date=a.start_date or a.end_date,
            end_date=a.end_date or a.start_date,
            source="custom",
            activity_id=a.id,
        ))
    # Kronologiskt, men egna aktiviteter utan datum sist så de inte stör inledningen
    result.sort(key=lambda i: (i.start_date is None, i.start_date or ""))
    return result


def next_activity_sort(activities) -> int:
    return max((a.sort_order or 0 for a in activities), default=-10) + 10
