#!/usr/bin/env bash
#
# Nattlig backup av Flow: databasdump, uppladdade filer och .env.
#
# Tänkt att komplettera – inte ersätta – serversnapshots hos hostingleverantören.
# Snapshotten räddar dig när maskinen dör; den här räddar dig när någon råkat
# radera fel kund och du bara vill ha tillbaka en tabell.
#
# Körs t.ex. från cron:
#   15 2 * * *  /opt/flow/scripts/backup.sh >> /var/log/flow-backup.log 2>&1
#
# Inställningar via miljövariabler (alla har rimliga standardvärden):
#   BACKUP_ROOT    var backuperna hamnar          (/var/backups/flow)
#   KEEP_DAILY     antal dagliga som sparas       (14)
#   KEEP_WEEKLY    antal veckovisa som sparas     (8)
#   KEEP_MONTHLY   antal månatliga som sparas     (12)
#
# Återställning beskrivs i scripts/RESTORE.md.

set -Eeuo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/flow}"
KEEP_DAILY="${KEEP_DAILY:-14}"
KEEP_WEEKLY="${KEEP_WEEKLY:-8}"
KEEP_MONTHLY="${KEEP_MONTHLY:-12}"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y-%m-%d_%H%M)"
STAGING="$BACKUP_ROOT/.staging-$STAMP"

log()  { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
fail() { log "FEL på rad $1 – backupen är INTE komplett"; rm -rf "$STAGING"; exit 1; }
trap 'fail $LINENO' ERR

log "=== Flow-backup startar ($STAMP) ==="

# ── Förberedelser ─────────────────────────────────────────────────────────────

cd "$PROJECT_DIR"

command -v docker >/dev/null || { log "FEL: docker saknas i PATH"; exit 1; }
docker compose version >/dev/null 2>&1 || { log "FEL: 'docker compose' (v2) krävs"; exit 1; }

# Databasnamn och användare måste matcha den körande containern. Samma
# standardvärden som docker-compose.yml använder när .env saknar dem.
# tr -d '\r' eftersom .env ofta redigeras på en Windows-maskin och då får CRLF –
# ett osynligt vagnreturtecken i databasnamnet ger ett mycket förvirrande fel.
env_value() {
    [ -f .env ] || return 0
    sed -n "s/^$1=//p" .env | tail -1 | tr -d '\r' | sed 's/^"\(.*\)"$/\1/'
}
PGUSER="$(env_value POSTGRES_USER)"; PGUSER="${PGUSER:-${POSTGRES_USER:-flow}}"
PGDB="$(env_value POSTGRES_DB)";     PGDB="${PGDB:-${POSTGRES_DB:-flow}}"

# Filerna ligger i en namngiven volym monterad i backend-containern. Genom att
# låna monteringarna med --volumes-from slipper vi gissa volymens prefixade namn
# (som beror på kataloge­namnet compose-projektet startades från).
BACKEND_CID="$(docker compose ps -q backend || true)"
if [ -z "$BACKEND_CID" ]; then
    log "FEL: backend-containern körs inte – kan inte nå uploads-volymen"
    exit 1
fi

mkdir -p "$STAGING"
chmod 700 "$STAGING"

# ── 1. Databasen ──────────────────────────────────────────────────────────────
# pg_dump inifrån containern, inte en filkopia av postgres_data: en kopia av en
# levande datakatalog kan fångas mitt i en transaktion. -Fc ger komprimerat
# custom-format som pg_restore kan läsa selektivt (t.ex. en enskild tabell).

log "Dumpar databasen ($PGDB)…"
docker compose exec -T db pg_dump -U "$PGUSER" -d "$PGDB" -Fc > "$STAGING/db.dump"

# En trunkerad dump ser ut som en lyckad backup tills dagen du behöver den.
# pg_restore --list läser innehållsförteckningen och avslöjar en trasig fil.
# Körs mot filen på disk i en egen container – att mata en custom-format-dump
# via stdin fungerar inte tillförlitligt eftersom pg_restore vill kunna söka.
if ! docker run --rm -v "$STAGING":/b postgres:16-alpine \
        pg_restore --list /b/db.dump > "$STAGING/db-innehall.txt" 2>/dev/null; then
    log "FEL: dumpen går inte att läsa med pg_restore – avbryter"
    exit 1
fi
log "Databasdump OK ($(du -h "$STAGING/db.dump" | cut -f1), $(wc -l < "$STAGING/db-innehall.txt") objekt)"

# ── 2. Uppladdade filer ───────────────────────────────────────────────────────
# Tas EFTER databasen med flit. Laddar någon upp en offert mellan de två stegen
# får vi en fil utan databasrad – ofarligt skräp. I omvänd ordning hade vi fått
# en databasrad utan fil, alltså en trasig nedladdning efter återställning.

log "Arkiverar uppladdade filer…"
docker run --rm \
    --volumes-from "$BACKEND_CID" \
    -v "$STAGING":/backup \
    alpine:latest \
    tar czf /backup/uploads.tar.gz -C /app/uploads . 2>/dev/null
log "Filarkiv OK ($(du -h "$STAGING/uploads.tar.gz" | cut -f1))"

# ── 3. Konfiguration ──────────────────────────────────────────────────────────
# .env innehåller POSTGRES_PASSWORD och SECRET_KEY. Utan den går det fortfarande
# att återställa (man sätter bara nya värden), men användarna loggas ut när
# SECRET_KEY byts. Lösenorden är bcrypt-hashade i databasen och överlever.

if [ -f .env ]; then
    cp .env "$STAGING/env.txt"
    log "Kopierade .env"
else
    log "VARNING: ingen .env hittades i $PROJECT_DIR"
fi

# ── 4. Manifest ───────────────────────────────────────────────────────────────
# Vilken kodversion dumpen hör till. Schemat skapas av models.py och
# _run_migrations() i main.py, så en dump utan känd commit är svår att tolka om
# den ska återställas långt senare.

{
    echo "Flow-backup"
    echo "Tidpunkt:     $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "Värd:         $(hostname)"
    echo "Projektkatalog: $PROJECT_DIR"
    echo "Git-commit:   $(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo 'okänd (ingen git-checkout)')"
    echo "Git-branch:   $(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'okänd')"
    echo "Databas:      $PGDB (användare $PGUSER)"
    echo
    echo "Körande images:"
    docker compose images 2>/dev/null | sed 's/^/  /' || echo "  kunde inte läsas"
    echo
    echo "Kontrollsummor:"
    (cd "$STAGING" && sha256sum db.dump uploads.tar.gz 2>/dev/null | sed 's/^/  /')
} > "$STAGING/MANIFEST.txt"

# ── 5. Placera och rotera ─────────────────────────────────────────────────────

DEST="$BACKUP_ROOT/daily/$STAMP"
mkdir -p "$BACKUP_ROOT/daily" "$BACKUP_ROOT/weekly" "$BACKUP_ROOT/monthly"
mv "$STAGING" "$DEST"
chmod -R go-rwx "$BACKUP_ROOT"
log "Sparad i $DEST"

# Hårda länkar istället för kopior – veckovisa och månatliga arkiv kostar då
# inget extra utrymme förrän den dagliga versionen rensas bort.
if [ "$(date +%u)" = "1" ]; then
    cp -al "$DEST" "$BACKUP_ROOT/weekly/$STAMP"
    log "Befordrad till veckoarkiv"
fi
if [ "$(date +%d)" = "01" ]; then
    cp -al "$DEST" "$BACKUP_ROOT/monthly/$STAMP"
    log "Befordrad till månadsarkiv"
fi

prune() {
    local dir="$1" keep="$2" total
    # Katalognamnen är YYYY-MM-DD_HHMM, så vanlig sortering är kronologisk.
    total="$(ls -1 "$dir" 2>/dev/null | wc -l)"
    [ "$total" -le "$keep" ] && return 0
    local name
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        rm -rf "${dir:?}/$name"
        log "Rensade $dir/$name"
    done < <(ls -1 "$dir" | sort | head -n "$((total - keep))")
}

prune "$BACKUP_ROOT/daily"   "$KEEP_DAILY"
prune "$BACKUP_ROOT/weekly"  "$KEEP_WEEKLY"
prune "$BACKUP_ROOT/monthly" "$KEEP_MONTHLY"

# ── 6. Kopia utanför maskinen ─────────────────────────────────────────────────
# Backup på samma server skyddar mot felaktig radering men inte mot att servern
# försvinner. Fyll i EN av varianterna nedan när det är bestämt vart den ska.
#
#   Nätverksplats/NAS (monterad sökväg):
#     rsync -a --delete "$BACKUP_ROOT/" /mnt/nas/flow-backup/
#
#   S3-kompatibel lagring eller molntjänst via rclone (konfigurera med
#   `rclone config` först – lägg aldrig nycklar i den här filen):
#     rclone sync "$BACKUP_ROOT" fjarr:flow-backup --transfers 4
#
offsite() {
    log "Offsite-steget är inte konfigurerat – backupen finns bara på $(hostname)"
}
offsite

log "=== Klart ==="
