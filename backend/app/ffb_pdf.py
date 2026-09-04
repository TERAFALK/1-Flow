"""De två dokumenten till Feldbinder som PDF.

Ritar om Word-mallarna kunden tidigare fyllde i för hand – "FFB Order" när en
affär är såld och "Quotation Request" när en offert ska begäras. Mallarna är
samma dokument så när som på rubriken och vilka rutor som finns i vänstra
spalten, så de delar ``_build`` här.

Layouten är kodad och bygger inte på Flows vanliga paneler
(``draw_info_panel``) – dokumenten ska se ut som FFB:s egna, inte som en
utskrift ur Flow.
"""
import io
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import getAscent, getDescent
from reportlab.pdfgen import canvas

from .pdf_utils import draw_header, truncate, wrap_lines
from .richtext import draw_rich_text

MARGIN = 18 * mm
PAGE_W, PAGE_H = A4
CONTENT_W = PAGE_W - 2 * MARGIN
COL_GAP = 8 * mm
COL_W = (CONTENT_W - COL_GAP) / 2
MIN_Y = 22 * mm            # lämnar plats åt sidfoten, som ligger på 14 mm

LABEL_SIZE = 9
VALUE_SIZE = 9
ROW_H = 4.6 * mm           # tätt som mallens 10-punktsrader
BOX_PAD = 3 * mm           # luft mellan text och ram i villkorsrutan

# Etiketterna på de två språken. Dokumenten till FFB är på engelska som mallen;
# den svenska varianten är samma uppgifter i ett underlag till slutkunden.
# Uppsättningen är fast och liten, så den är översatt en gång för hand – ingen
# maskinöversättning inblandad, och därmed inget som kan bli fel över tid.
LABELS = {
    "en": {
        "customer": "Customer:", "country": "Country:", "phone": "Phone:",
        "mail": "Mail:", "contact": "Contact pers:",
        "date": "Date:", "vat": "VAT nr:", "customer_nr": "Customer nr:",
        "chassis_info": "Chassis info",
        "terms_payment": "Terms of Payment", "terms_delivery": "Terms of Delivery:",
        "quotation_title": "Quotation Request",
        "quotation_info": "Quotation info",
        "quotation_text": "Quotation request text",
        "typ": "Typ:", "volume": "Volume approx.", "transport": "Transport of:",
        "reg_country": "Country of registration:", "drawing": "According to drawing:",
        "special": "Special feature:",
        "chassis": "Chassi:", "wheelbase": "Wheel base:", "fo": "FO Number:",
    },
    "sv": {
        "customer": "Kund:", "country": "Land:", "phone": "Telefon:",
        "mail": "E-post:", "contact": "Kontaktperson:",
        "date": "Datum:", "vat": "VAT-nummer:", "customer_nr": "Kundnummer:",
        "chassis_info": "Chassiuppgifter",
        "terms_payment": "Betalningsvillkor", "terms_delivery": "Leveransvillkor:",
        "quotation_title": "Offertförfrågan",
        "quotation_info": "Offertuppgifter",
        "quotation_text": "Offertförfrågan, text",
        "typ": "Typ:", "volume": "Volym ca", "transport": "Transport av:",
        "reg_country": "Registreringsland:", "drawing": "Enligt ritning:",
        "special": "Övrigt:",
        "chassis": "Chassi:", "wheelbase": "Hjulbas:", "fo": "FO-nummer:",
    },
}

# Villkoren är data och inte etiketter, så de översätts inte i allmänhet. De två
# förtryckta standardtexterna är däremot våra egna kända strängar, och att låta
# dem stå på engelska under en svensk rubrik ser bara slarvigt ut. Har kunden
# skrivit en egen text lämnas den ifred – då är det hans formulering som gäller.
DEFAULT_TERMS_SV = {
    "10% Down payment, 90% on completion without deduction":
        "10 % handpenning, 90 % vid färdigställande utan avdrag",
    "DAT Gothenburg": "DAT Göteborg",
}


def _term(value, lang):
    return DEFAULT_TERMS_SV.get(_v(value), value) if lang == "sv" else value


# Måtten står i mallens sidhuvud (2275166 × 462958 EMU)
LOGO_W = 63 * mm
LOGO_H = 12.9 * mm
_LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "ffb-logo.jpg")
_logo = None


def _get_logo():
    """Loggan läses en gång och återanvänds. Saknas den ska beställningen ändå
    gå att skriva ut – texten är det FFB behöver."""
    global _logo
    if _logo is None:
        try:
            _logo = ImageReader(_LOGO_PATH)
        except Exception:
            _logo = False
    return _logo


def _v(value) -> str:
    """Tomma fält skrivs ut som tom sträng, inte "None"."""
    if value is None:
        return ""
    return str(value).strip()


class _Doc:
    """Canvas med y-läge, sidhuvud och sidfot.

    ``ffb`` styr avsändaren. Dokumenten som går till Feldbinder bär FFB:s
    logotyp och deras klassningsrad i sidfoten, precis som mallen. Den svenska
    kopian går till slutkunden och ska då se ut som ett dokument härifrån – där
    används Flows eget sidhuvud i stället.
    """

    def __init__(self, title: str, ffb: bool = True):
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=A4)
        self.title = title
        self.ffb = ffb
        self.y = self._header()

    def _header(self) -> float:
        c = self.c
        if not self.ffb:
            return draw_header(c, PAGE_W, self.title) - 4 * mm

        top = PAGE_H - 15 * mm
        logo = _get_logo()
        if logo:
            c.drawImage(logo, MARGIN, top - LOGO_H, width=LOGO_W, height=LOGO_H,
                        mask="auto", preserveAspectRatio=True, anchor="sw")
        else:
            c.setFont("Helvetica-Bold", 16)
            c.setFillColor(colors.HexColor("#EE7203"))
            c.drawString(MARGIN, top - 10, "FELDBINDER")
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 16)
        c.drawRightString(PAGE_W - MARGIN, top - LOGO_H + 2 * mm, self.title)
        return top - LOGO_H - 10 * mm

    def _footer(self):
        # "Limited Distribution." är FFB:s egen klassning och hör inte hemma på
        # ett dokument som går vidare till slutkunden
        if not self.ffb:
            return
        self.c.setFont("Helvetica", 7.5)
        self.c.setFillColor(colors.HexColor("#8a8f96"))
        self.c.drawString(MARGIN, 14 * mm, "Limited Distribution.")
        self.c.setFillColor(colors.black)

    def new_page(self) -> float:
        self._footer()
        self.c.showPage()
        self.y = self._header()
        return self.y

    def space(self, needed: float):
        if self.y - needed < MIN_Y:
            self.new_page()

    def rule(self):
        self.c.setStrokeColor(colors.HexColor("#c3ccd6"))
        self.c.setLineWidth(0.8)
        self.c.line(MARGIN, self.y, PAGE_W - MARGIN, self.y)
        self.y -= 5 * mm

    def body(self, text: str, font_size=9.5, leading=13):
        """Brödtexten, med fetstil, kursiv, punktlistor och tabbar som kunden
        satt i redigeraren. Sidbrytningen sköts av ``new_page`` så att sidfoten
        kommer med på varje sida."""
        self.c.setFillColor(colors.black)
        self.y = draw_rich_text(
            self.c, text, MARGIN, self.y, CONTENT_W,
            font_size=font_size, leading=leading,
            min_y=MIN_Y, on_new_page=self.new_page,
        )

    def section(self, left_title: str, right_title: str = ""):
        """Avsnittsrubrik(er) med linje under, som mallens gråa band."""
        self.space(16 * mm)
        self.c.setFont("Helvetica-Bold", 9.5)
        self.c.setFillColor(colors.black)
        self.c.drawString(MARGIN, self.y, left_title)
        if right_title:
            self.c.drawString(MARGIN + COL_W + COL_GAP, self.y, right_title)
        self.y -= 3 * mm
        self.rule()


def _rows(c: canvas.Canvas, x: float, y: float, width: float, rows) -> float:
    """Etikett/värde-rader i mallens stil: fet etikett med värdet under.

    Ett värde som inte ryms bryts över flera rader i stället för att kapas –
    "Special feature" och adresser blir annars obrukbara hos FFB. Returnerar
    y-läget under sista raden.
    """
    for label, value in rows:
        value = _v(value)
        if label:
            c.setFont("Helvetica-Bold", LABEL_SIZE)
            c.setFillColor(colors.HexColor("#333333"))
            c.drawString(x, y, truncate(label, "Helvetica-Bold", LABEL_SIZE, width))
            y -= ROW_H
        c.setFont("Helvetica", VALUE_SIZE)
        c.setFillColor(colors.black)
        for line in (wrap_lines(value, "Helvetica", VALUE_SIZE, width) if value else [""]):
            c.drawString(x, y, line)
            y -= ROW_H
    return y


def _block_height(rows, width) -> float:
    """Höjden ett block kommer att ta, så att sidbrytningen kan tas i förväg."""
    height = 0.0
    for label, value in rows:
        if label:
            height += ROW_H
        value = _v(value)
        lines = wrap_lines(value, "Helvetica", VALUE_SIZE, width) if value else [""]
        height += ROW_H * len(lines)
    return height


def _build(*, title, doc_date, cust, info_title, info_rows,
           chassis_rows, terms_payment, terms_delivery,
           body_title, body_text, lang="en") -> io.BytesIO:
    """Den gemensamma sidan. Skillnaden mellan order och offertförfrågan är
    rubrikerna och vilka rader som står i vänstra spalten."""
    doc = _Doc(title, ffb=lang == "en")
    c = doc.c
    L = LABELS[lang]

    # ── Kunden till vänster, datum/VAT/kundnummer till höger ─────────────────
    # Mallen flyttar de två tabellerna bredvid varandra med tblpPr, så de ska
    # börja på samma höjd.
    customer = [
        (L["customer"], cust.get("customer_name")),
        ("", cust.get("address")),
        ("", cust.get("postal_city")),
        (L["country"], cust.get("country")),
        (L["phone"], cust.get("phone")),
        (L["mail"], cust.get("email")),
        (L["contact"], cust.get("contact_person")),
    ]
    head = [
        (L["date"], doc_date.isoformat() if doc_date else ""),
        (L["vat"], cust.get("vat_number")),
        (L["customer_nr"], cust.get("customer_number")),
    ]
    doc.space(max(_block_height(customer, COL_W), _block_height(head, COL_W)) + 4 * mm)
    y_top = doc.y
    y1 = _rows(c, MARGIN, y_top, COL_W, customer)
    y2 = _rows(c, MARGIN + COL_W + COL_GAP, y_top, COL_W, head)
    doc.y = min(y1, y2) - 4 * mm

    # ── Vänstra spalten och Chassis info ─────────────────────────────────────
    doc.section(info_title, L["chassis_info"])
    doc.space(max(_block_height(info_rows, COL_W), _block_height(chassis_rows, COL_W)) + 4 * mm)
    y_top = doc.y
    y1 = _rows(c, MARGIN, y_top, COL_W, info_rows)
    y2 = _rows(c, MARGIN + COL_W + COL_GAP, y_top, COL_W, chassis_rows)
    doc.y = min(y1, y2) - 6 * mm

    # ── Villkor ──────────────────────────────────────────────────────────────
    terms = [
        (L["terms_payment"], _term(terms_payment, lang)),
        (L["terms_delivery"], _term(terms_delivery, lang)),
    ]
    # Ramen räknas ut från textens verkliga över- och underkant i stället för
    # från radhöjden. Radhöjden är avståndet mellan baslinjer och säger inget om
    # var bokstäverna börjar, så den gav en ram som satt tajt upptill och
    # glappade nedtill.
    inner_w = CONTENT_W - 12 * mm
    lines = round(_block_height(terms, inner_w) / ROW_H)
    ascent = getAscent("Helvetica-Bold", LABEL_SIZE)
    descent = -getDescent("Helvetica", VALUE_SIZE)
    box_h = (lines - 1) * ROW_H + ascent + descent + 2 * BOX_PAD

    doc.space(box_h)
    box_top = doc.y
    c.setStrokeColor(colors.HexColor("#c3ccd6"))
    c.setLineWidth(0.8)
    c.rect(MARGIN, box_top - box_h, CONTENT_W, box_h, fill=0, stroke=1)
    _rows(c, MARGIN + 6 * mm, box_top - BOX_PAD - ascent, inner_w, terms)
    doc.y = box_top - box_h - 6 * mm

    # ── Brödtexten ───────────────────────────────────────────────────────────
    doc.section(body_title)
    doc.body(body_text or "")

    doc._footer()
    c.save()
    doc.buf.seek(0)
    return doc.buf


def build_ffb_order_pdf(ffb, cust: dict) -> io.BytesIO:
    """Beställningen på en såld affär – mallen "FFB Order".

    ``cust`` är kundblocket, som hämtas ur kunden vid utskrift i stället för att
    ligga lagrat på posten – se ``routers.ffb_orders.customer_block``.
    """
    return _build(
        lang="en",
        title="Order",
        doc_date=ffb.doc_date,
        cust=cust,
        info_title="Order info",
        info_rows=[
            ("Quantity:", ffb.quantity),
            ("Quotation nr:", ffb.quotation_number),
            ("Delivery time:", ffb.delivery_time),
            ("Typ:", ffb.product_type),
            ("Volume approx.", ffb.volume_approx),
            ("Transport of:", ffb.transport_of),
            ("Country of registration:", ffb.country_of_registration),
            ("According to drawing:", ffb.drawing_number),
            ("Special feature:", ffb.special_feature),
        ],
        chassis_rows=[
            ("Chassi:", ffb.chassis_make),
            ("Wheel base:", ffb.wheel_base),
            ("FO Number:", ffb.fo_number),
            ("Delivery time:", ffb.chassis_delivery_time),
            ("Part No:", ffb.part_no),
            ("Delivery time:", ffb.part_delivery_time),
        ],
        terms_payment=ffb.terms_payment,
        terms_delivery=ffb.terms_delivery,
        body_title="Order text",
        body_text=ffb.order_text,
    )


def build_ffb_quote_pdf(quote, cust: dict, lang: str = "en") -> io.BytesIO:
    """Offertförfrågan – mallen "Quotation Request".

    Samma dokument som ordern men utan antal, offertnummer och leveranstider:
    de är inte bestämda än när man ber om ett pris.

    ``lang="en"`` är dokumentet som går till FFB. ``lang="sv"`` är samma
    uppgifter som underlag till slutkunden: svenska etiketter, Flows eget
    sidhuvud och utan FFB:s logotyp och klassningsrad.
    """
    L = LABELS[lang]
    return _build(
        lang=lang,
        title=L["quotation_title"],
        doc_date=quote.doc_date,
        cust=cust,
        info_title=L["quotation_info"],
        info_rows=[
            (L["typ"], quote.product_type),
            (L["volume"], quote.volume_approx),
            (L["transport"], quote.transport_of),
            (L["reg_country"], quote.country_of_registration),
            (L["drawing"], quote.drawing_number),
            (L["special"], quote.special_feature),
        ],
        chassis_rows=[
            (L["chassis"], quote.chassis_make),
            (L["wheelbase"], quote.wheel_base),
            (L["fo"], quote.fo_number),
        ],
        terms_payment=quote.terms_payment,
        terms_delivery=quote.terms_delivery,
        body_title=L["quotation_text"],
        body_text=quote.request_text,
    )
