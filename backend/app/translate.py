"""Översättning av fritext via DeepL.

Används av offertförfrågan: dokumentet till FFB skrivs på engelska, och den
svenska versionen behöver samma text på svenska. Etiketterna i dokumenten
översätts inte här – de är en fast ordlista i ``ffb_pdf.LABELS``. Det som går
hit är bara det kunden själv skrivit.

Översättningen sker när någon trycker på knappen, inte när PDF:en hämtas.
Resultatet sparas och får redigeras innan det skickas: maskinöversatt teknisk
text blir fel på just de ord som betyder mest (hjulbas, manlucka,
framkomstintyg), och ett dokument som går vidare till en kund ska någon ha läst.

Nyckeln sätts med DEEPL_API_KEY. Saknas den är funktionen avstängd och knappen
döljs i gränssnittet – resten av offertförfrågan fungerar som vanligt.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from .richtext import balance_tags

def _read_key() -> str:
    """Nyckeln ur miljön, städad.

    Citattecken tas bort: skriver man DEEPL_API_KEY="abc:fx" i .env följer de
    med in i värdet. Då slutar nyckeln inte längre på ":fx", anropet går till
    fel värd och DeepL svarar 403 – ett fel som är svårt att gissa sig till.
    """
    raw = os.getenv("DEEPL_API_KEY", "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        raw = raw[1:-1].strip()
    return raw


API_KEY = _read_key()
TIMEOUT = 15


class TranslationError(Exception):
    """Fel som är begripligt att visa för användaren."""


def is_configured() -> bool:
    return bool(API_KEY)


def _host() -> str:
    # Gratisnycklar slutar på ":fx" och går mot en annan värd. Att läsa av det
    # ur nyckeln sparar en inställning som ändå bara kan sättas fel.
    return "api-free.deepl.com" if API_KEY.endswith(":fx") else "api.deepl.com"


def _endpoint() -> str:
    return f"https://{_host()}/v2/translate"


def translate_html(texts: list, target_lang: str = "SV") -> list:
    """Översätter en lista texter och returnerar dem i samma ordning.

    Texterna är den lilla delmängd HTML som redigeraren sparar, så anropet görs
    med ``tag_handling=html`` – då överlever fetstil, kursiv och punktlistor
    översättningen i stället för att komma tillbaka som taggar i löptexten.

    Tomma texter skickas aldrig iväg utan lämnas som de är.
    """
    if not is_configured():
        raise TranslationError("Ingen DEEPL_API_KEY är satt på servern")

    # Håll reda på vilka platser som faktiskt har text att översätta
    positions = [i for i, t in enumerate(texts) if (t or "").strip()]
    if not positions:
        return list(texts)

    out = list(texts)
    # DeepL tar högst 50 texter per anrop. En lång specifikation delad per rad
    # och spalt blir lätt fler än så.
    for start in range(0, len(positions), MAX_TEXTS_PER_REQUEST):
        chunk = positions[start:start + MAX_TEXTS_PER_REQUEST]
        translated = _request([texts[i] for i in chunk], target_lang)
        for position, text in zip(chunk, translated):
            out[position] = text
    return out


# DeepL:s gräns för antal texter i ett anrop
MAX_TEXTS_PER_REQUEST = 50


def _request(texts: list, target_lang: str) -> list:
    """Ett anrop mot DeepL med en redan filtrerad, icke-tom lista texter."""
    fields = [("target_lang", target_lang), ("tag_handling", "html")]
    fields += [("text", text) for text in texts]
    body = urllib.parse.urlencode(fields).encode()

    request = urllib.request.Request(
        _endpoint(),
        data=body,
        headers={
            "Authorization": f"DeepL-Auth-Key {API_KEY}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise TranslationError(_http_message(exc.code)) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TranslationError("Kunde inte nå DeepL – kontrollera serverns internetanslutning") from exc
    except json.JSONDecodeError as exc:
        raise TranslationError("Oväntat svar från DeepL") from exc

    translations = payload.get("translations") or []
    if len(translations) != len(texts):
        raise TranslationError("DeepL svarade med fel antal översättningar")
    return [t.get("text", original) for t, original in zip(translations, texts)]


# ── Struktur ──────────────────────────────────────────────────────────────────
# Det som bär textens form och därför aldrig får skickas till DeepL: rad-
# brytningar, tabbar (Chrome lindar dem i <span style="white-space:pre">),
# blocktaggar och indrag av två eller fler blanksteg.
#
# I HTML-läge fäller DeepL ihop blanksteg, precis som en webbläsare gör – ett
# radbrytningstecken blir ett mellanslag och ett indrag på tolv blanksteg blir
# ett. Skickas texten som den är kommer den tillbaka som en enda lång rad.
_STRUCTURE = re.compile(
    r"(\r?\n"
    r"|<span\b[^>]*>[ \t]+</span>"
    r"|\t+"
    r"|</?(?:div|p|ul|ol|li|br)\b[^>]*>"
    r"|(?:&nbsp;| ){2,})",
    re.I,
)


def _has_text(fragment: str) -> bool:
    without_tags = re.sub(r"<[^>]+>", "", fragment)
    return bool(re.sub(r"&nbsp;|&#160;|\s", "", without_tags))


def translate_structured(values: list, target_lang: str = "SV") -> list:
    """Översätter formaterad text och behåller dess form exakt.

    Varje värde delas i struktur och text. Strukturen – radbrytningar, tabbar,
    indrag, blocktaggar – sätts tillbaka tecken för tecken, och bara textbitarna
    däremellan skickas till DeepL. En teknisk specifikation med rubrik i
    vänsterkant och indragna rader under kommer då tillbaka med samma layout.

    Fetstil och kursiv följer med textbitarna, så DeepL kan flytta dem rätt när
    ordföljden ändras. En fetstil som korsar en tabb delas i två balanserade
    delar innan den skickas; resultatet ser likadant ut men är välformat, vilket
    DeepL kräver för att hantera taggarna.

    Priset är att en mening som Word bröt mitt itu över en tabb översätts som
    två delar. Det är ett mindre fel än att hela layouten försvinner.
    """
    plans = []
    queue = []
    for value in values:
        plan = []
        for index, part in enumerate(_STRUCTURE.split(value or "")):
            # Udda index är det som matchade mönstret, alltså strukturen
            if index % 2 == 1 or not _has_text(part):
                plan.append(part)
                continue
            core = part.strip()
            lead = part[:len(part) - len(part.lstrip())]
            trail = part[len(part.rstrip()):]
            plan.append((lead, len(queue), trail))
            queue.append(balance_tags(core))
        plans.append(plan)

    translated = translate_html(queue, target_lang) if queue else []

    return [
        "".join(
            piece if isinstance(piece, str) else piece[0] + translated[piece[1]] + piece[2]
            for piece in plan
        )
        for plan in plans
    ]


def _http_message(code: int) -> str:
    # 403 betyder både "fel nyckel" och "rätt nyckel mot fel värd", så värden
    # och nyckelns slut nämns: slutar den på ":fx" ska anropet gå till
    # api-free, annars till api.deepl.com. Nyckeln själv skrivs aldrig ut.
    if code == 403:
        return (
            f"DeepL nekade nyckeln (anropet gick till {_host()}). "
            f"Nyckeln är {len(API_KEY)} tecken och slutar "
            f"{'på :fx' if API_KEY.endswith(':fx') else 'inte på :fx'} – "
            "kontrollera att DEEPL_API_KEY är rätt kopierad och utan citattecken."
        )
    return {
        429: "För många anrop till DeepL just nu, försök igen om en stund",
        456: "DeepL-kvoten är slut för den här månaden",
    }.get(code, f"DeepL svarade med fel {code}")
