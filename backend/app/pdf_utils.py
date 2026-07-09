import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
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
