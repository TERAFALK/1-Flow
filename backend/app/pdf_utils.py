import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import simpleSplit
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
