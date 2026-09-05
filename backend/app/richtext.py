"""Formaterad brödtext från gränssnittet till PDF.

De långa fritextfälten som blir underlag i en PDF (FFB-beställningen,
offertförfrågan och arbetsorderns brödtext) redigeras med fetstil, kursiv,
understruket, punktlistor och tabbar. Innehållet sparas som en liten delmängd
HTML och ritas här med ReportLabs ``Paragraph``, som klarar inline-taggar och
radbrytning på ett sätt som ``canvas.drawString`` inte gör.

Allt som kommer in är skrivet av en användare och kan innehålla vad som helst –
inklustrad text från Word, en ensam ``<`` eller ett halvt taggpar. Därför
plockas texten isär med en egen parser som bara släpper igenom de taggar vi
själva kan skapa, och allt annat blir vanlig text.
"""
import html
import re
from html.parser import HTMLParser

from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

# Taggar redigeraren kan skapa. Allt annat blir text.
_INLINE = {"b": "b", "strong": "b", "i": "i", "em": "i", "u": "u"}
_BLOCK = {"div", "p", "li", "ul", "ol", "br"}

# Bara taggar redigeraren kan skapa räknas som markup. Ett värde med ett ensamt
# "<" i sig ("5 < 6", "<ren> text") är vanlig text och ska escapas, inte tolkas.
# span finns med för att Chrome lindar infogade tabbar i
# <span style="white-space:pre">; utan den läses en text vars enda tagg är den
# spannen som ren text, och taggen skrivs ut synligt i dokumentet.
_HAS_MARKUP = re.compile(r"</?(?:b|strong|i|em|u|br|div|p|ul|ol|li|span)\b[^>]*>", re.I)

# En tabb blir fast bredd i PDF:en. Paragraph fäller ihop vanliga blanksteg,
# så det måste vara hårda mellanslag för att kolumnerna ska hålla.
TAB = "&nbsp;" * 8


def plain_text(value: str) -> str:
    """Texten utan formatering – för listvyer och sammanfattningar."""
    without_tags = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(html.unescape(without_tags).split())


class _Block:
    """Ett stycke: raden som ska ritas plus om den är en punkt i en lista."""

    def __init__(self, markup: str, bullet: bool):
        self.markup = markup
        self.bullet = bullet


class _Parser(HTMLParser):
    """Plockar isär redigerarens HTML till stycken med inline-markup kvar."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Block] = []
        self._parts: list[str] = []
        self._open: list[str] = []
        self._bullet = False
        self._in_list = 0

    # ── stycken ──────────────────────────────────────────────────────────────
    def _flush(self, explicit: bool = False):
        """Avslutar stycket. Taggar som fortfarande är öppna stängs här och
        öppnas igen i nästa stycke, så att varje stycke för sig är balanserat –
        ``Paragraph`` fallerar annars på en fetstil som korsar en radbrytning.

        ``explicit`` skiljer en radbrytning användaren gjort (``<br>`` eller ett
        ``\\n``) från en ren strukturgräns (``</div>`` följt av ``<div>``). Den
        första ska ge en tom rad när det inte står något emellan, den andra ska
        inte det – annars hamnar en blankrad mellan varje rad i texten.
        """
        markup = "".join(self._parts + [f"</{t}>" for t in reversed(self._open)]).strip()
        # Ett stycke som bara består av taggar (t.ex. en fetstil som stängdes av
        # en radbrytning) har inget att visa och räknas som en tom rad
        if not plain_text(markup):
            markup = ""
        if markup or explicit:
            self.blocks.append(_Block(markup, self._bullet))
        self._parts = [f"<{t}>" for t in self._open]

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _INLINE:
            self._open.append(_INLINE[tag])
            self._parts.append(f"<{_INLINE[tag]}>")
        elif tag == "br":
            self._flush(explicit=True)
        elif tag == "li":
            self._flush()
            self._bullet = True
        elif tag in ("ul", "ol"):
            self._flush()
            self._in_list += 1
        elif tag in _BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _INLINE:
            close = _INLINE[tag]
            if close in self._open:
                # Stäng i rätt ordning även om texten är slarvigt nästlad
                while self._open and self._open[-1] != close:
                    self._parts.append(f"</{self._open.pop()}>")
                self._open.pop()
                self._parts.append(f"</{close}>")
        elif tag == "li":
            self._flush()
            self._bullet = False
        elif tag in ("ul", "ol"):
            self._flush()
            self._in_list = max(0, self._in_list - 1)
            self._bullet = False
        elif tag in _BLOCK:
            self._flush()

    def handle_data(self, data):
        # Ett fält med white-space: pre-wrap kan få ett rent radbrytningstecken
        # i stället för <br> när användaren trycker Enter. Varje rad blir därför
        # ett eget stycke, annars klistras texten ihop till en enda röra.
        lines = data.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        for i, line in enumerate(lines):
            if i:
                self._flush(explicit=True)
            # Taggarna i _parts är våra egna, så bara den riktiga texten escapas
            self._parts.append(html.escape(line, quote=False).replace("\t", TAB))

    def close(self):
        super().close()
        self._flush()


def to_blocks(value: str) -> list:
    """Gör lagrad text till stycken redo för ``Paragraph``.

    Text utan taggar behandlas som ren text – fälten var vanliga textrutor förut
    och gamla värden ska renderas precis som de skrevs.
    """
    value = (value or "").strip()
    if not value:
        return []

    if not _HAS_MARKUP.search(value):
        return [
            _Block(html.escape(line, quote=False).replace("\t", TAB) or "&nbsp;", False)
            for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        ]

    parser = _Parser()
    parser.feed(value)
    parser.close()

    blocks = parser.blocks
    # Tomma rader först och sist är rester ur redigerarens markup, inte något
    # användaren skrivit. Tomma rader mitt i texten är däremot styckeindelning
    # och ska vara kvar.
    while blocks and not blocks[0].markup:
        blocks.pop(0)
    while blocks and not blocks[-1].markup:
        blocks.pop()
    for block in blocks:
        if not block.markup:
            block.markup = "&nbsp;"
    return blocks


def draw_rich_text(c, value, x, y, width, *, font_name="Helvetica", font_size=9.5,
                   leading=13, min_y, on_new_page, bullet_indent=5) -> float:
    """Ritar formaterad brödtext och returnerar y-läget under sista raden.

    ``on_new_page`` ska bryta sidan, rita sidhuvudet och returnera nytt y-läge.
    Ett stycke som inte får plats delas över sidbrytningen i stället för att
    flyttas i sin helhet – ett långt stycke ska inte lämna en halvtom sida.
    """
    style = ParagraphStyle(
        "rich", fontName=font_name, fontSize=font_size, leading=leading,
    )
    bullet_style = ParagraphStyle(
        "rich-bullet", parent=style,
        leftIndent=bullet_indent + 8, bulletIndent=bullet_indent,
    )

    for block in to_blocks(value):
        # bulletText låter Paragraph rita punkten själv, så den hamnar rätt även
        # när stycket delas över en sidbrytning
        para = Paragraph(
            block.markup,
            bullet_style if block.bullet else style,
            bulletText="•" if block.bullet else None,
        )
        while True:
            _, height = para.wrap(width, max(y - min_y, 0))
            if height <= y - min_y:
                para.drawOn(c, x, y - height)
                y -= height
                break

            # Får inte plats: dela stycket vid sidbrytningen om det går
            parts = para.split(width, max(y - min_y, 0))
            if len(parts) < 2:
                y = on_new_page()
                continue
            head, rest = parts[0], parts[1]
            _, head_h = head.wrap(width, y - min_y)
            head.drawOn(c, x, y - head_h)
            y = on_new_page()
            para = rest
    return y
