# Återställa Flow från backup

En backup som aldrig har återställts är en gissning. Gå igenom **Test av återställning**
längst ner en gång i kvartalet – det tar tjugo minuter och är enda sättet att veta att
det här fungerar.

Varje backup ligger i en egen katalog, t.ex. `/var/backups/flow/daily/2026-08-23_0215/`:

| Fil | Innehåll |
|---|---|
| `db.dump` | Hela databasen i Postgres custom-format |
| `uploads.tar.gz` | Uppladdade filer – arbetsorderbilagor och offert-PDF:er |
| `env.txt` | Kopia av `.env` (lösenord och `SECRET_KEY`) |
| `MANIFEST.txt` | Tidpunkt, git-commit, images och kontrollsummor |
| `db-innehall.txt` | Innehållsförteckning över dumpen |

Läs alltid `MANIFEST.txt` först. **Git-commiten avgör vilken kodversion schemat hör till** –
återställer du en gammal dump mot nyare kod kan tabeller saknas.

---

## Fall 1: En enskild rad är felaktigt raderad

Vanligaste fallet, och det som serversnapshots är dåliga på. Rör aldrig produktions-
databasen – ställ upp en tillfällig kopia bredvid och plocka ut det du behöver.

```bash
docker run -d --name flow-temp -e POSTGRES_PASSWORD=temp -e POSTGRES_USER=flow -e POSTGRES_DB=flow postgres:16-alpine
```

Läs in dumpen i den tillfälliga databasen:

```bash
docker run --rm -i --link flow-temp -v /var/backups/flow/daily/2026-08-23_0215:/b postgres:16-alpine pg_restore -h flow-temp -U flow -d flow /b/db.dump
```

Titta på det du letar efter:

```bash
docker exec -it flow-temp psql -U flow -d flow -c "SELECT * FROM customers WHERE name ILIKE '%Hyllinge%';"
```

Kopiera sedan över raden manuellt till produktion (via appen eller ett `INSERT`), och städa upp:

```bash
docker rm -f flow-temp
```

> Tänk på ordningen om du för över en säljaffär: kunden måste finnas innan `sales_leads`,
> och förfrågan innan `sales_orders`. Milstolpsraderna återskapas automatiskt av
> `_ensure_milestones` i `routers/sales_orders.py` när ordern öppnas.

---

## Fall 2: Hela systemet ska upp igen

Till exempel på en ny server efter ett haveri.

**1. Ta upp koden i rätt version.** Använd git-commiten ur `MANIFEST.txt`:

```bash
git clone <repo> /opt/flow && git -C /opt/flow checkout <commit-ur-manifestet>
```

**2. Lägg tillbaka konfigurationen.** Kopiera `env.txt` till `/opt/flow/.env`. Behåller du
samma `SECRET_KEY` slipper alla logga in på nytt; byter du den blir alla utloggade, men
inget data går förlorat – lösenorden är bcrypt-hashade i databasen.

**3. Starta bara databasen först**, så att backend inte hinner köra migrationerna mot en
tom databas:

```bash
cd /opt/flow && docker compose up -d db
```

**4. Läs in dumpen.** `--clean --if-exists` gör kommandot körbart flera gånger utan att
det uppstår dubbletter:

```bash
docker compose exec -T db pg_restore -U flow -d flow --clean --if-exists < /sokvag/till/backup/db.dump
```

**5. Lägg tillbaka filerna.** Volymen måste finnas, så starta backend och packa sedan upp
arkivet i den:

```bash
docker compose up -d backend
docker run --rm --volumes-from "$(docker compose ps -q backend)" -v /sokvag/till/backup:/b alpine tar xzf /b/uploads.tar.gz -C /app/uploads
```

**6. Starta resten och kontrollera:**

```bash
docker compose up -d
```

Logga in och verifiera i den här ordningen – det är de tre saker som brukar fela:

- Öppna en kund och se att arbetsorder och fordon finns kvar.
- Öppna en **såld order** under Försäljning och kontrollera att milstolparna har kvar sina datum.
- Öppna en **förfrågan med en offert-PDF** och klicka **Hämta**. Går filen inte att ladda ner
  kom `uploads.tar.gz` inte på plats – databasen har raden men volymen saknar byten.

---

## Test av återställning (kvartalsvis)

Gör detta mot en **separat** compose-stack, aldrig mot produktionen. Enklast är att kopiera
projektkatalogen till `/tmp/flow-test` och köra med ett eget projektnamn så att volymerna
inte krockar:

```bash
cp -r /opt/flow /tmp/flow-test && cd /tmp/flow-test && docker compose -p flowtest up -d db
```

Kör sedan steg 4–6 ovan med `-p flowtest` på varje `docker compose`-kommando, gör
kontrollerna, och riv ner alltihop inklusive volymerna när du är klar:

```bash
cd /tmp/flow-test && docker compose -p flowtest down -v && rm -rf /tmp/flow-test
```

Notera hur lång tid det tog. Den siffran är svaret när kunden frågar hur länge systemet
ligger nere om något går sönder.
