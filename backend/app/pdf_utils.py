import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "logo.svg")
_logo_drawing = None
_logo_size = (0, 0)


def _get_logo():
    global _logo_drawing, _logo_size
    if _logo_drawing is not None:
        return _logo_drawing
    try:
        from svglib.svglib import svg2rlg
        drawing = svg2rlg(_LOGO_PATH)
        _logo_drawing = drawing
        _logo_size = (drawing.width, drawing.height)
    except Exception:
        _logo_drawing = False
    return _logo_drawing


def draw_header(c: canvas.Canvas, page_width, title: str, subtitle: str = "", top_y=None):
    """Draws the Flow logo top-left and a title, returns the y-position to continue below.

    ``top_y`` defaults to the top of an A4 *portrait* page. Pass an explicit value
    (t.ex. ``page_height - 10*mm``) för liggande/andra sidstorlekar."""
    margin = 18 * mm
    if top_y is None:
        top_y = 287 * mm
    drawing = _get_logo()
    if drawing:
        target_w = 45 * mm
        scale = target_w / drawing.width
        drawing.width *= scale
        drawing.height *= scale
        drawing.scale(scale, scale)
        drawing.drawOn(c, margin, top_y - drawing.height)
        text_x = margin + target_w + 8 * mm
    else:
        c.setFont("Helvetica-Bold", 18)
        c.setFillColor(colors.HexColor("#E2001A"))
        c.drawString(margin, top_y - 12, "FLOW")
        text_x = margin + 40 * mm

    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(text_x, top_y - 12, title)
    if subtitle:
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.HexColor("#666666"))
        c.drawString(text_x, top_y - 26, subtitle)
        c.setFillColor(colors.black)

    c.setStrokeColor(colors.HexColor("#E2001A"))
    c.setLineWidth(1.2)
    c.line(margin, top_y - 32, page_width - margin, top_y - 32)
    return top_y - 42


def wrap_lines(text: str, font_name: str, font_size: float, max_width: float):
    """Bryter text till rader som ryms inom ``max_width``.

    Tomma rader i källtexten bevaras så att styckeindelningen i en arbetstext
    följer med till PDF:en."""
    out = []
    for paragraph in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not paragraph.strip():
            out.append("")
            continue
        out.extend(simpleSplit(paragraph, font_name, font_size, max_width) or [""])
    return out


def truncate(text, font_name: str, font_size: float, max_width: float) -> str:
    """Kortar text med avslutande ellips så att den ryms inom ``max_width``."""
    text = str(text if text is not None else "")
    if stringWidth(text, font_name, font_size) <= max_width:
        return text
    while text and stringWidth(text + "…", font_name, font_size) > max_width:
        text = text[:-1]
    return (text + "…") if text else ""


def draw_info_panel(c: canvas.Canvas, x, y_top, width, title, rows,
                    accent="#2f6fed", row_h=14, font_size=8.5):
    """Ritar en rubricerad etikett/värde-panel och returnerar panelens underkant.

    ``rows`` är (etikett, värde)-par; par med tomt värde hoppas över så att en
    ofullständigt ifylld post inte ger tomma rader. Värden kortas för att aldrig
    krocka med etiketten."""
    rows = [(lbl, str(val)) for lbl, val in rows if val not in (None, "", "None")]
    label_w = width * 0.42
    value_w = width - label_w - 18
    inner_w = width - 16

    # Värden som inte ryms bredvid etiketten (kundnamn, chassinr …) läggs på egen
    # rad i full bredd istället för att kapas
    laid = [
        (lbl, val, stringWidth(val, "Helvetica-Bold", font_size) > value_w)
        for lbl, val in rows
    ]
    head_h = 16 if title else 6
    height = head_h + sum(row_h * (2 if stacked else 1) for _, _, stacked in laid) + 8

    c.setFillColor(colors.HexColor(accent))
    c.setFillAlpha(0.05)
    c.roundRect(x, y_top - height, width, height, 6, fill=1, stroke=0)
    c.setFillAlpha(1)
    c.setStrokeColor(colors.HexColor("#c3ccd6"))
    c.setLineWidth(0.8)
    c.roundRect(x, y_top - height, width, height, 6, fill=0, stroke=1)

    y = y_top - 12
    if title:
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(colors.HexColor(accent))
        c.drawString(x + 8, y, title.upper())
        y -= head_h - 2

    for label, value, stacked in laid:
        c.setFont("Helvetica", font_size)
        c.setFillColor(colors.HexColor("#5a6675"))
        c.drawString(x + 8, y, truncate(label, "Helvetica", font_size, label_w if not stacked else inner_w))
        c.setFont("Helvetica-Bold", font_size)
        c.setFillColor(colors.black)
        if stacked:
            y -= row_h
            c.drawRightString(x + width - 8, y, truncate(value, "Helvetica-Bold", font_size, inner_w))
        else:
            c.drawRightString(x + width - 8, y, truncate(value, "Helvetica-Bold", font_size, value_w))
        y -= row_h
    return y_top - height


def draw_paragraph(c: canvas.Canvas, text: str, x, y, max_width, font_name="Helvetica",
                   font_size=9.5, leading=13, min_y=25 * mm, on_new_page=None):
    """Ritar brödtext med radbrytning och automatiska sidbrytningar.

    ``on_new_page`` anropas efter varje sidbrytning och ska returnera nytt y-läge.
    Returnerar y-positionen under sista raden."""
    c.setFont(font_name, font_size)
    for line in wrap_lines(text, font_name, font_size, max_width):
        if y < min_y:
            c.showPage()
            y = on_new_page() if on_new_page else (287 * mm)
            c.setFont(font_name, font_size)
        if line:
            c.drawString(x, y, line)
        y -= leading
    return y
