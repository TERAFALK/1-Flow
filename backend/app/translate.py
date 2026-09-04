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
import urllib.error
import urllib.parse
import urllib.request

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

    fields = [("target_lang", target_lang), ("tag_handling", "html")]
    fields += [("text", texts[i]) for i in positions]
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
    if len(translations) != len(positions):
        raise TranslationError("DeepL svarade med fel antal översättningar")

    out = list(texts)
    for position, translation in zip(positions, translations):
        out[position] = translation.get("text", texts[position])
    return out


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
