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
from reportlab.pdfbase.pdfmetrics import stringWidth
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

# Tabbstopp var åttonde tecken, som i en vanlig texteditor.
TAB_COLUMNS = 8
# Tabbarna märks ut medan raden bearbetas. En tabb är ett avsiktligt
# spaltavstånd, till skillnad från blanksteg som lika gärna är vanlig text, och
# skillnaden behövs för att känna igen en spaltrad. Tecknet kan aldrig komma in
# med texten – HTML-parsern släpper inte igenom det.
TAB_MARK = "\x00"


def plain_text(value: str) -> str:
    """Texten utan formatering – för listvyer och sammanfattningar."""
    without_tags = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(html.unescape(without_tags).split())


def _expand_tabs(markup: str) -> str:
    """Byter tabbar mot blanksteg fram till nästa tabbstopp.

    Kolumnen räknas på den synliga texten – taggarna (<b>, <i>, <u>) syns inte i
    dokumentet och ska därför inte flytta tabbstoppen. En teckenentitet som
    &amp; räknas som ett tecken av samma skäl.
    """
    out = []
    column = 0
    i = 0
    while i < len(markup):
        char = markup[i]
        if char == "<":                      # tagg – hoppa över, räknas inte
            end = markup.find(">", i)
            if end == -1:
                out.append(markup[i:])
                break
            out.append(markup[i:end + 1])
            i = end + 1
        elif char == "&":                     # entitet – ett synligt tecken
            end = markup.find(";", i)
            if end == -1 or end - i > 10:
                out.append(char); column += 1; i += 1
            else:
                out.append(markup[i:end + 1]); column += 1; i = end + 1
        elif char == "\t":
            width = TAB_COLUMNS - (column % TAB_COLUMNS)
            out.append(TAB_MARK * width)
            column += width
            i += 1
        else:
            out.append(char); column += 1; i += 1
    return "".join(out)


def _split_indent(markup: str):
    """Delar av radens inledande blanksteg och returnerar (text, indrag).

    Indraget bär strukturen i en teknisk specifikation – rubrik i vänsterkant,
    innehållet indraget under. Det ritas som ett marginalindrag i stället för
    som blanksteg, så att en rad som bryts fortsätter under sin egen indragning
    i stället för att hoppa ut till vänsterkanten.
    """
    match = re.match(r"^((?:<[^>]+>)*)([ " + TAB_MARK + r"]*)", markup)
    tags, blanks = match.group(1), match.group(2)
    return tags + markup[match.end():], len(blanks)


# Var beskrivningsspalten börjar, som andel av textbredden
LABEL_FRACTION = 0.30
# Längre än så är det ingen etikett utan en mening som råkat innehålla en tabb
MAX_LABEL_CHARS = 40
# Beskrivningsspalten måste börja så här långt in. En enstaka tabb tidigt på
# raden ("Artikel<tabb>Antal<tabb>Pris") är en tabell och ska behålla sina
# kolumner; en villkorslista har beskrivningen långt ut till höger.
MIN_BODY_COLUMN = 24


def _balance(markup: str) -> str:
    """Gör ett taggfragment fristående.

    Taggar som lämnats öppna stängs sist, och taggar som stängs utan att ha
    öppnats i fragmentet öppnas först. Behövs när en rad delas i två spalter:
    snittet kan gå rakt igenom en fetstil, och ``Paragraph`` fallerar på ett
    fragment som inte är balanserat för sig.
    """
    open_tags = []
    reopen = []
    for match in re.finditer(r"</?(\w+)>", markup):
        tag = match.group(1)
        if match.group(0).startswith("</"):
            if tag in open_tags:
                # Stäng till och med taggen, även om nästlingen är slarvig
                while open_tags and open_tags.pop() != tag:
                    pass
            else:
                reopen.append(tag)
        else:
            open_tags.append(tag)
    # Taggarna som ska öppnas först är de som stängs sist: "c</i></b>" var en
    # gång "<b><i>c</i></b>", så prefixet måste bli <b><i> och inte <i><b>.
    return (
        "".join(f"<{t}>" for t in reversed(reopen))
        + markup
        + "".join(f"</{t}>" for t in reversed(open_tags))
    )


def _visible_column(markup: str) -> int:
    """Antal synliga tecken i markup – taggar och entiteter räknas som noll
    respektive ett, precis som när tabbarna expanderades."""
    without_tags = re.sub(r"<[^>]+>", "", markup)
    return len(re.sub(r"&[A-Za-z]+;|&#\d+;", ".", without_tags))


def _split_label(markup: str):
    """Delar en spaltrad i (etikett, beskrivning), annars ``(None, raden)``.

    Villkorslistor skrivna i Word ("tank colour" + tabbar + en lång text) blir
    vid inklistring en enda rad där tabbarna både skiljer spalterna åt och
    ersätter de radbrytningar Word gjorde i högerspalten. Ritas de rakt av blir
    resultatet trasigt. Känner vi igen mönstret kan beskrivningen i stället få
    en egen spalt och brytas där, som i ursprungsdokumentet.

    Etiketten måste vara kort. En tabb mitt i en lång mening är inte en spalt
    utan en rest från Words radbrytning, och den raden ska bara flyta på.
    Anropas bara för rader som börjar i vänsterkanten, där spalterna sitter.
    """
    match = re.search(r"\S[ " + TAB_MARK + r"]*" + TAB_MARK, markup)
    if not match:
        return None, markup
    label = markup[:match.start() + 1]
    body = markup[match.end():]
    if not plain_text(label) or not plain_text(body):
        return None, markup
    if len(plain_text(label)) > MAX_LABEL_CHARS:
        return None, markup
    if _visible_column(markup[:match.end()]) < MIN_BODY_COLUMN:
        return None, markup
    # De återstående mellanrummen i beskrivningen är Words radbrytningar och
    # ska bli vanliga ordmellanrum, inte hål i texten
    body = re.sub(r"[ " + TAB_MARK + r"]{2,}", " ", body).strip()
    # Delningen kan gå rakt igenom en fetstil ("<b>FFB type<tabb>...</b>"), och
    # då blir båda halvorna obalanserade var för sig. Paragraph kräver att varje
    # fragment står på egna ben.
    return _balance(label.rstrip().replace(TAB_MARK, " ")), _balance(body)


def _keep_gaps(markup: str) -> str:
    """Behåller mellanrum inuti raden.

    ``Paragraph`` fäller ihop flera blanksteg till ett, så kolumner satta med
    blanksteg eller tabbar skulle falla samman. Enkla blanksteg lämnas som de
    är, annars går texten inte att radbryta.
    """
    markup = markup.replace(TAB_MARK, " ")
    return re.sub(r" {2,}", lambda m: "&nbsp;" * len(m.group()), markup)


class _Block:
    """Ett stycke: raden som ska ritas, om den är en punkt i en lista, och hur
    många teckenbredder den är indragen."""

    def __init__(self, markup: str, bullet: bool, indent: int = 0, label: str = ""):
        self.markup = markup
        self.bullet = bullet
        self.indent = indent
        # Satt när raden är en spaltrad: etiketten i vänsterspalten
        self.label = label


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
        markup = "".join(self._parts + [f"</{t}>" for t in reversed(self._open)])
        # Ett stycke som bara består av taggar eller blanktecken har inget att
        # visa och räknas som en tom rad
        if not plain_text(markup):
            markup = ""
        if markup:
            markup, indent = _split_indent(_expand_tabs(markup))
            # Spalter förekommer bara på rader som börjar i vänsterkanten. En
            # indragen rad hör till stycket ovanför och ska flyta på som text.
            label, markup = _split_label(markup.rstrip()) if not indent else (None, markup.rstrip())
            markup = markup if label else _keep_gaps(markup)
            self.blocks.append(_Block(markup, self._bullet, indent, label or ""))
        elif explicit:
            self.blocks.append(_Block("", self._bullet))
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
            # Taggarna i _parts är våra egna, så bara den riktiga texten escapas.
            # Blanksteg och tabbar lämnas orörda – de behandlas i _flush, där
            # hela raden finns och kolumnerna går att räkna.
            self._parts.append(html.escape(line, quote=False))

    def close(self):
        super().close()
        self._flush()


def to_blocks(value: str) -> list:
    """Gör lagrad text till stycken redo för ``Paragraph``.

    Text utan taggar behandlas som ren text – fälten var vanliga textrutor förut
    och gamla värden ska renderas precis som de skrevs.
    """
    value = (value or "").strip("\r\n")
    if not value.strip():
        return []

    if not _HAS_MARKUP.search(value):
        # Ren text går genom samma väg som markup, så indrag och mellanrum
        # behandlas likadant oavsett var värdet kommer ifrån
        parser = _Parser()
        parser.feed(html.escape(value, quote=False))
        parser.close()
    else:
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


def _paragraph(markup: str, style, **kwargs) -> Paragraph:
    """``Paragraph`` med skyddsnät.

    Texten är skriven av en användare och går genom flera omskrivningar innan
    den hamnar här. Skulle något fragment ändå bli markup ReportLab inte
    accepterar ska dokumentet tappa formateringen på den raden – inte fallera.
    Utskriften sker under sparningen av formuläret, så ett undantag här skulle
    annars göra att ingenting alls gick att spara.
    """
    try:
        return Paragraph(markup, style, **kwargs)
    except Exception:
        return Paragraph(html.escape(plain_text(markup), quote=False), style, **kwargs)


def _draw_label_row(c, block, x, y, width, label_col, style, *, min_y, on_new_page):
    """Ritar en spaltrad och returnerar y-läget under den.

    Raden hålls ihop: får den inte plats flyttas hela raden till nästa sida i
    stället för att etiketten blir ensam kvar. Är beskrivningen längre än en
    hel sida delas den ändå, annars hade den aldrig fått plats.
    """
    label = _paragraph(block.label, style)
    body = _paragraph(block.markup, style)
    label_w = max(label_col - 6, 20)
    body_w = width - label_col

    _, label_h = label.wrap(label_w, 10_000)
    _, body_h = body.wrap(body_w, 10_000)
    height = max(label_h, body_h)

    if y - height < min_y:
        # Ryms inte på det som är kvar av sidan – pröva en tom sida först, så
        # att etiketten inte blir ensam kvar längst ned
        y = on_new_page()

    if y - height >= min_y:
        label.drawOn(c, x, y - label_h)
        body.drawOn(c, x + label_col, y - body_h)
        return y - height

    # Längre än en hel sida: etiketten på första sidan, beskrivningen delas
    label.drawOn(c, x, y - label_h)
    while True:
        _, body_h = body.wrap(body_w, max(y - min_y, 0))
        if body_h <= y - min_y:
            body.drawOn(c, x + label_col, y - body_h)
            return y - body_h
        parts = body.split(body_w, max(y - min_y, 0))
        if len(parts) < 2:
            y = on_new_page()
            continue
        head, body = parts[0], parts[1]
        _, head_h = head.wrap(body_w, y - min_y)
        head.drawOn(c, x + label_col, y - head_h)
        y = on_new_page()


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
    # Indraget mäts i teckenbredder, som i redigeraren där texten skrevs
    space_width = stringWidth(" ", font_name, font_size)
    label_col = width * LABEL_FRACTION
    indent_styles = {}

    for block in to_blocks(value):
        if block.label:
            # Spaltrad: etiketten till vänster, beskrivningen i egen spalt som
            # bryts där. Fortsättningsrader med stort indrag hamnar i samma
            # spalt, så en flerradig post hänger ihop.
            y = _draw_label_row(
                c, block, x, y, width, label_col, style,
                min_y=min_y, on_new_page=on_new_page,
            )
            continue

        if block.bullet:
            block_style = bullet_style
        elif block.indent:
            # Marginalindrag och inte blanksteg: en rad som bryts fortsätter då
            # under sin egen indragning i stället för ute i vänsterkanten
            block_style = indent_styles.get(block.indent)
            if block_style is None:
                block_style = ParagraphStyle(
                    f"rich-{block.indent}", parent=style,
                    leftIndent=min(block.indent * space_width, label_col),
                )
                indent_styles[block.indent] = block_style
        else:
            block_style = style

        # bulletText låter Paragraph rita punkten själv, så den hamnar rätt även
        # när stycket delas över en sidbrytning
        para = _paragraph(
            block.markup,
            block_style,
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
