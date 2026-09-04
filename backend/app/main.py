import os
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import engine, get_db
from . import models
from .auth import hash_password
from .routers import (
    auth, users, customers, vehicles, articles,
    work_orders, time_entries, dashboard,
    settings, contacts, phases, purchases, files, activities, tasks,
    pick_lists, sales_leads, sales_orders, sales_milestones, ffb_orders, notes,
)

models.Base.metadata.create_all(bind=engine)

# ── Schema migrations (idempotent ALTER TABLE for new columns) ─────────────────
def _run_migrations():
    from sqlalchemy import text
    stmts = [
        # work_orders – new columns
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS body_text TEXT",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS contact_person_id INTEGER REFERENCES contact_persons(id) ON DELETE SET NULL",
        # purchases – header description is now optional (lines carry the articles)
        "ALTER TABLE purchases ALTER COLUMN description DROP NOT NULL",
        """CREATE TABLE IF NOT EXISTS purchase_lines (
            id SERIAL PRIMARY KEY,
            purchase_id INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
            article_id INTEGER REFERENCES articles(id) ON DELETE SET NULL,
            description VARCHAR NOT NULL,
            article_number VARCHAR,
            quantity NUMERIC DEFAULT 1,
            unit VARCHAR DEFAULT 'st'
        )""",
        # articles – new columns
        "ALTER TABLE articles ADD COLUMN IF NOT EXISTS supplier VARCHAR",
        # vehicles – new columns
        "ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS kraftuttag VARCHAR",
        "ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS utvaxling VARCHAR",
        "ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS rotation VARCHAR",
        "ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS medbringare VARCHAR",
        "ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS wheelbase_mm INTEGER",
        "ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS width_mm INTEGER",
        "ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS front_overhang_mm INTEGER",
        "ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS rear_overhang_mm INTEGER",
        "ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS max_steering_angle DOUBLE PRECISION",
        "ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS axles JSONB",
        "ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS axle_load JSONB",
        # contact_persons
        """CREATE TABLE IF NOT EXISTS contact_persons (
            id SERIAL PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            name VARCHAR NOT NULL,
            title VARCHAR,
            phone VARCHAR,
            email VARCHAR,
            is_primary BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        # work_order_phases
        """CREATE TABLE IF NOT EXISTS work_order_phases (
            id SERIAL PRIMARY KEY,
            work_order_id INTEGER NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
            name VARCHAR NOT NULL,
            color VARCHAR DEFAULT '#E2001A',
            start_date DATE,
            end_date DATE,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        # purchases – need enum type first
        "DO $$ BEGIN CREATE TYPE purchasestatus AS ENUM ('beställd','inlevererad','avbeställd'); EXCEPTION WHEN duplicate_object THEN null; END $$",
        "ALTER TYPE purchasestatus ADD VALUE IF NOT EXISTS 'ej_beställd' BEFORE 'beställd'",
        """CREATE TABLE IF NOT EXISTS purchases (
            id SERIAL PRIMARY KEY,
            work_order_id INTEGER NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
            purchase_number VARCHAR,
            supplier VARCHAR,
            description VARCHAR,
            article_number VARCHAR,
            quantity NUMERIC,
            delivery_week INTEGER,
            status purchasestatus DEFAULT 'beställd',
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        # work_order_files
        "DO $$ BEGIN CREATE TYPE filetype AS ENUM ('document','photo','drawing'); EXCEPTION WHEN duplicate_object THEN null; END $$",
        """CREATE TABLE IF NOT EXISTS work_order_files (
            id SERIAL PRIMARY KEY,
            work_order_id INTEGER NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
            filename VARCHAR NOT NULL,
            original_name VARCHAR NOT NULL,
            file_type filetype NOT NULL,
            mime_type VARCHAR,
            size_bytes BIGINT,
            uploaded_at TIMESTAMP DEFAULT NOW(),
            uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL
        )""",
        # activities
        "DO $$ BEGIN CREATE TYPE activitytype AS ENUM ('samtal','händelse','anteckning'); EXCEPTION WHEN duplicate_object THEN null; END $$",
        """CREATE TABLE IF NOT EXISTS activities (
            id SERIAL PRIMARY KEY,
            work_order_id INTEGER NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
            activity_type activitytype NOT NULL DEFAULT 'anteckning',
            description TEXT NOT NULL,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        # tasks
        """CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            work_order_id INTEGER NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
            title VARCHAR NOT NULL,
            description TEXT,
            assigned_to INTEGER REFERENCES users(id) ON DELETE SET NULL,
            due_date DATE,
            completed BOOLEAN DEFAULT FALSE,
            completed_at TIMESTAMP,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        # settings
        """CREATE TABLE IF NOT EXISTS settings (
            key VARCHAR PRIMARY KEY,
            value VARCHAR NOT NULL
        )""",
        # pick lists
        """CREATE TABLE IF NOT EXISTS pick_lists (
            id SERIAL PRIMARY KEY,
            title VARCHAR NOT NULL,
            notes TEXT,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS pick_list_lines (
            id SERIAL PRIMARY KEY,
            pick_list_id INTEGER NOT NULL REFERENCES pick_lists(id) ON DELETE CASCADE,
            article_id INTEGER REFERENCES articles(id) ON DELETE SET NULL,
            description VARCHAR NOT NULL,
            quantity NUMERIC DEFAULT 1,
            unit VARCHAR DEFAULT 'st',
            location VARCHAR,
            picked BOOLEAN DEFAULT FALSE
        )""",
        # Artikelnummer på raderna – överlever tömning/ominläsning av artikelregistret
        "ALTER TABLE work_order_lines ADD COLUMN IF NOT EXISTS article_number VARCHAR",
        "ALTER TABLE pick_list_lines ADD COLUMN IF NOT EXISTS article_number VARCHAR",
        "CREATE INDEX IF NOT EXISTS ix_work_order_lines_article_number ON work_order_lines (article_number)",
        "CREATE INDEX IF NOT EXISTS ix_pick_list_lines_article_number ON pick_list_lines (article_number)",
        # Backfill av befintliga rader som fortfarande har kvar sin artikelkoppling
        """UPDATE work_order_lines l SET article_number = a.article_number
           FROM articles a WHERE l.article_id = a.id AND l.article_number IS NULL""",
        """UPDATE pick_list_lines l SET article_number = a.article_number
           FROM articles a WHERE l.article_id = a.id AND l.article_number IS NULL""",
        """UPDATE purchase_lines l SET article_number = a.article_number
           FROM articles a WHERE l.article_id = a.id AND l.article_number IS NULL""",
        # ── Försäljning / CRM ─────────────────────────────────────────────────
        "DO $$ BEGIN CREATE TYPE salesleadstatus AS ENUM ('ny','skickad','jobbar','sald','avslutad'); EXCEPTION WHEN duplicate_object THEN null; END $$",
        "DO $$ BEGIN CREATE TYPE salesnotekind AS ENUM ('samtal','mail','mote','anteckning'); EXCEPTION WHEN duplicate_object THEN null; END $$",
        "DO $$ BEGIN CREATE TYPE milestonevaluetype AS ENUM ('datum','text','ja_nej'); EXCEPTION WHEN duplicate_object THEN null; END $$",
        """CREATE TABLE IF NOT EXISTS sales_leads (
            id SERIAL PRIMARY KEY,
            activity_number VARCHAR,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            contact_person_id INTEGER REFERENCES contact_persons(id) ON DELETE SET NULL,
            product_type VARCHAR,
            size VARCHAR,
            quantity INTEGER DEFAULT 1,
            status salesleadstatus NOT NULL DEFAULT 'ny',
            date_request DATE,
            date_sent_ffb DATE,
            date_back_ffb DATE,
            date_sent_customer DATE,
            quote_number VARCHAR,
            estimated_value NUMERIC(12,2),
            currency VARCHAR DEFAULT 'EUR',
            next_followup_date DATE,
            assigned_to INTEGER REFERENCES users(id) ON DELETE SET NULL,
            external_link VARCHAR,
            lost_reason VARCHAR,
            notes TEXT,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_sales_leads_status ON sales_leads (status)",
        "CREATE INDEX IF NOT EXISTS ix_sales_leads_activity_number ON sales_leads (activity_number)",
        "CREATE INDEX IF NOT EXISTS ix_sales_leads_quote_number ON sales_leads (quote_number)",
        "CREATE INDEX IF NOT EXISTS ix_sales_leads_next_followup_date ON sales_leads (next_followup_date)",
        """CREATE TABLE IF NOT EXISTS sales_lead_notes (
            id SERIAL PRIMARY KEY,
            lead_id INTEGER NOT NULL REFERENCES sales_leads(id) ON DELETE CASCADE,
            note_date DATE NOT NULL DEFAULT CURRENT_DATE,
            kind salesnotekind NOT NULL DEFAULT 'anteckning',
            body TEXT NOT NULL,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS sales_lead_files (
            id SERIAL PRIMARY KEY,
            lead_id INTEGER NOT NULL REFERENCES sales_leads(id) ON DELETE CASCADE,
            filename VARCHAR NOT NULL,
            original_name VARCHAR NOT NULL,
            mime_type VARCHAR,
            size_bytes BIGINT,
            uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            uploaded_at TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS sales_orders (
            id SERIAL PRIMARY KEY,
            lead_id INTEGER REFERENCES sales_leads(id) ON DELETE SET NULL,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            order_number VARCHAR,
            serial_number VARCHAR,
            product_type VARCHAR,
            price NUMERIC(12,2),
            currency VARCHAR DEFAULT 'EUR',
            commission NUMERIC(12,2),
            commission_paid_date DATE,
            sold_date DATE,
            delivery_date DATE,
            planned_delivery DATE,
            delivery_week VARCHAR,
            registration_number VARCHAR,
            weight_kg INTEGER,
            visit_ffb BOOLEAN DEFAULT FALSE,
            sort_index INTEGER,
            notes TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_sales_orders_order_number ON sales_orders (order_number)",
        "CREATE INDEX IF NOT EXISTS ix_sales_orders_sold_date ON sales_orders (sold_date)",
        """CREATE TABLE IF NOT EXISTS sales_milestone_defs (
            id SERIAL PRIMARY KEY,
            key VARCHAR NOT NULL UNIQUE,
            group_label VARCHAR NOT NULL,
            label VARCHAR NOT NULL,
            value_type milestonevaluetype NOT NULL DEFAULT 'datum',
            sort_order INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE
        )""",
        """CREATE TABLE IF NOT EXISTS sales_order_milestones (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
            def_id INTEGER NOT NULL REFERENCES sales_milestone_defs(id) ON DELETE CASCADE,
            value_date DATE,
            value_text VARCHAR,
            completed BOOLEAN DEFAULT FALSE,
            updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            updated_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT uq_order_milestone UNIQUE (order_id, def_id)
        )""",
        # AOC blev egna rader – en order kan ha flera intyg (NB001, NB002, NB003)
        """CREATE TABLE IF NOT EXISTS sales_order_aocs (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
            aoc_number VARCHAR,
            sent_customer DATE,
            mailed_ffb DATE,
            cost_eur NUMERIC(12,2),
            notes TEXT,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        # Bilagor per avsnitt (group_label) eller per AOC (aoc_id)
        """CREATE TABLE IF NOT EXISTS sales_order_files (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
            group_label VARCHAR,
            aoc_id INTEGER REFERENCES sales_order_aocs(id) ON DELETE CASCADE,
            filename VARCHAR NOT NULL,
            original_name VARCHAR NOT NULL,
            mime_type VARCHAR,
            size_bytes BIGINT,
            uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            uploaded_at TIMESTAMP DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_sales_order_files_group ON sales_order_files (group_label)",
        # Kundens önskemål: FO-nr hör hemma bland ritningarna, inte under betalning.
        # Seeden rör inte befintliga rader (ON CONFLICT DO NOTHING), så flytten
        # måste göras här för installationer som redan har milstolpen.
        "UPDATE sales_milestone_defs SET group_label = 'Ritningar' WHERE key = 'fo_nr'",
        # De fyra AOC-milstolparna ersätts av sales_order_aocs. Raderna behålls
        # inaktiva så att inget redan ifyllt värde raderas.
        """UPDATE sales_milestone_defs SET is_active = FALSE
           WHERE key IN ('aoc_nr','aoc_skickad_kund','aoc_mailat_ffb','aoc_kostnad_eur')""",
        # Best effort-flytt av redan ifyllda AOC-värden till den nya tabellen.
        # Texterna behålls ordagrant i notes istället för att gissa datum – flera
        # celler innehöll två värden ("NB002    NB003"). NOT EXISTS gör satsen
        # idempotent så en omstart inte skapar dubbletter.
        """INSERT INTO sales_order_aocs (order_id, aoc_number, notes, sort_order, created_at)
           SELECT m.order_id,
                  MAX(CASE WHEN d.key = 'aoc_nr' THEN m.value_text END),
                  NULLIF(concat_ws(chr(10),
                      MAX(CASE WHEN d.key = 'aoc_skickad_kund' THEN 'Skickad – kund: ' || m.value_text END),
                      MAX(CASE WHEN d.key = 'aoc_mailat_ffb'   THEN 'Mailat – FFB: '   || m.value_text END),
                      MAX(CASE WHEN d.key = 'aoc_kostnad_eur'  THEN 'Kostnad EUR: '    || m.value_text END)
                  ), ''),
                  0, NOW()
           FROM sales_order_milestones m
           JOIN sales_milestone_defs d ON d.id = m.def_id
           WHERE d.key IN ('aoc_nr','aoc_skickad_kund','aoc_mailat_ffb','aoc_kostnad_eur')
             AND NULLIF(btrim(m.value_text), '') IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM sales_order_aocs a WHERE a.order_id = m.order_id)
           GROUP BY m.order_id""",
        # Uppföljningen ska fortsätta efter att affären gått igenom, så en
        # anteckning kan nu hänga på en order istället för en förfrågan.
        "ALTER TABLE sales_lead_notes ADD COLUMN IF NOT EXISTS order_id INTEGER REFERENCES sales_orders(id) ON DELETE CASCADE",
        "ALTER TABLE sales_lead_notes ALTER COLUMN lead_id DROP NOT NULL",
        # Avslutade ordrar arkiveras istället för att raderas
        "ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP",
        "CREATE INDEX IF NOT EXISTS ix_sales_orders_archived_at ON sales_orders (archived_at)",
        # Egna aktiviteter i Gantt-schemat, på förfrågan eller order
        """CREATE TABLE IF NOT EXISTS sales_activities (
            id SERIAL PRIMARY KEY,
            lead_id INTEGER REFERENCES sales_leads(id) ON DELETE CASCADE,
            order_id INTEGER REFERENCES sales_orders(id) ON DELETE CASCADE,
            name VARCHAR NOT NULL,
            color VARCHAR DEFAULT '#E2001A',
            start_date DATE,
            end_date DATE,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_sales_activities_lead ON sales_activities (lead_id)",
        "CREATE INDEX IF NOT EXISTS ix_sales_activities_order ON sales_activities (order_id)",
        # ── Två sorters förfrågningar ─────────────────────────────────────────
        # Feldbinder-affärer (hela FFB-kedjan) och verkstadsofferter, som istället
        # blir en arbetsorder när de säljs. Befintliga rader är feldbinder.
        "DO $$ BEGIN CREATE TYPE salesleadkind AS ENUM ('feldbinder','verkstad'); EXCEPTION WHEN duplicate_object THEN null; END $$",
        "ALTER TABLE sales_leads ADD COLUMN IF NOT EXISTS kind salesleadkind NOT NULL DEFAULT 'feldbinder'",
        "CREATE INDEX IF NOT EXISTS ix_sales_leads_kind ON sales_leads (kind)",
        "ALTER TABLE sales_leads ADD COLUMN IF NOT EXISTS description TEXT",
        "ALTER TABLE sales_leads ADD COLUMN IF NOT EXISTS work_order_id INTEGER REFERENCES work_orders(id) ON DELETE SET NULL",
        "ALTER TABLE sales_leads ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP",
        "CREATE INDEX IF NOT EXISTS ix_sales_leads_archived_at ON sales_leads (archived_at)",
        # Uppgifter och anteckningar kan nu hänga direkt på en kund – en förfrågan
        # som varken är offert eller affär ska gå att logga ändå. CASCADE eftersom
        # de är anteckningar och inte affärsposter; offerter och ordrar blockerar
        # fortfarande radering av kunden (se routers/customers.py).
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE",
        "CREATE INDEX IF NOT EXISTS ix_tasks_customer_id ON tasks (customer_id)",
        "ALTER TABLE sales_lead_notes ADD COLUMN IF NOT EXISTS customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE",
        "CREATE INDEX IF NOT EXISTS ix_sales_lead_notes_customer_id ON sales_lead_notes (customer_id)",
        # Bilagor kan nu hänga på en enskild anteckning – mailet och korten som kom
        # in i samband med kontakten sparas per aktivitet istället för i en hög.
        "ALTER TABLE sales_lead_files ADD COLUMN IF NOT EXISTS note_id INTEGER REFERENCES sales_lead_notes(id) ON DELETE CASCADE",
        "ALTER TABLE sales_lead_files ALTER COLUMN lead_id DROP NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_sales_lead_files_note_id ON sales_lead_files (note_id)",
        # Uppgifter kan nu ligga på en offert och flyttas till arbetsordern vid försäljning
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS lead_id INTEGER REFERENCES sales_leads(id) ON DELETE CASCADE",
        "ALTER TABLE tasks ALTER COLUMN work_order_id DROP NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_tasks_lead_id ON tasks (lead_id)",
        # ── Beställning till Feldbinder ───────────────────────────────────────
        # FFB-beställningen är på engelska och vill ha uppgifter vi inte har
        # frågat efter tidigare. De hör till kunden, inte till en enskild order.
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS vat_number VARCHAR",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS country VARCHAR",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS ffb_customer_number VARCHAR",
        # Själva beställningen. En rad per order, skapad förifylld första gången
        # den öppnas – därför inga värden att migrera för redan sålda ordrar.
        """CREATE TABLE IF NOT EXISTS ffb_orders (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL UNIQUE REFERENCES sales_orders(id) ON DELETE CASCADE,
            doc_date DATE,
            vat_number VARCHAR,
            customer_number VARCHAR,
            customer_name VARCHAR,
            address VARCHAR,
            postal_city VARCHAR,
            country VARCHAR,
            phone VARCHAR,
            email VARCHAR,
            contact_person VARCHAR,
            quantity VARCHAR,
            quotation_number VARCHAR,
            delivery_time VARCHAR,
            product_type VARCHAR,
            part_no VARCHAR,
            part_delivery_time VARCHAR,
            volume_approx VARCHAR,
            transport_of VARCHAR,
            country_of_registration VARCHAR,
            drawing_number VARCHAR,
            special_feature VARCHAR,
            chassis_make VARCHAR,
            wheel_base VARCHAR,
            fo_number VARCHAR,
            chassis_delivery_time VARCHAR,
            terms_payment VARCHAR,
            terms_delivery VARCHAR,
            order_text TEXT,
            updated_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_ffb_orders_order_id ON ffb_orders (order_id)",
    ]
    with engine.connect() as conn:
        for stmt in stmts:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                print(f"Migration warning: {e}")
        conn.commit()

_run_migrations()


def _migrate_roles():
    """Collapse legacy roles (chef/mekaniker/lager) to 'tekniker'."""
    from sqlalchemy import text
    # A newly added enum value must be committed before it can be used, so run
    # the ADD VALUE in its own autocommit connection.
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'tekniker'"))
    except Exception as e:
        print(f"Role migration warning (add value): {e}")
    try:
        with engine.connect() as conn:
            conn.execute(text("UPDATE users SET role = 'tekniker' WHERE role <> 'admin'"))
            conn.commit()
    except Exception as e:
        print(f"Role migration warning (update): {e}")


_migrate_roles()


# ── Milstolpar för sålda affärer ──────────────────────────────────────────────
# Stegen är hämtade från årsflikarna 2025/2026 i kundens Excel. De seedas som
# data (inte kolumner) eftersom uppsättningen har ändrats varje år, och kunden
# kan redigera dem under Inställningar. value_type 'text' används där Excel-
# cellerna innehåller fritext snarare än ett datum ("x", "NB001 NB002",
# "Finns ej enl FFB", eller två datum i samma cell när ordern har två AOC).
# sort_order står uttryckligen i varje rad – inte som listindex – eftersom
# befintliga installationer redan har sina värden och seeden inte skriver över
# dem. Att lägga till eller ta bort en rad här får därför inte flytta de andra.
# AOC saknas med flit: de intygen är egna rader i sales_order_aocs sedan
# kunden behövde kunna ha flera per order.
SALES_MILESTONE_SEED = [
    # (key, group_label, label, value_type, sort_order)
    ("orderbekraftelse",        "Order & betalning",    "Orderbekräftelse",             "datum",   0),
    ("bankpapper",              "Order & betalning",    "Bankpapper",                   "text",   10),
    ("faktura_10",              "Order & betalning",    "Faktura 10 %",                 "datum",  20),
    ("faktura_10_betald",       "Order & betalning",    "Faktura 10 % betald",          "datum",  30),
    ("order_signerad",          "Order & betalning",    "Order signerad",               "datum",  40),
    ("fo_nr",                   "Ritningar",            "FO-nr",                        "text",   50),
    ("chassi_info",             "Ritningar",            "Chassi info",                  "datum",  60),
    ("ritning_komplett",        "Ritningar",            "Komplett ritning med chassi",  "datum",  70),
    ("lack_forslag_kund",       "Lackering",            "Förslag – kund",               "datum",  80),
    ("lack_forslag_ffb",        "Lackering",            "Förslag – FFB",                "datum",  90),
    ("lack_slutlig_kund",       "Lackering",            "Slutlig – kund",               "datum", 100),
    ("lack_slutlig_ffb",        "Lackering",            "Slutlig – FFB",                "datum", 110),
    ("agare_fordon",            "Registrering",         "Ägare / fordon",               "text",  120),
    ("ursprungskontroll",       "Registrering",         "Ursprungskontroll ansökan",    "datum", 130),
    ("ursprung_paskrift_kund",  "Registrering",         "För påskrift av kund",         "datum", 140),
    ("ursprung_postad_ts",      "Registrering",         "Postad till TS",               "datum", 150),
    # 160–190 var AOC-milstolparna. AOC_SECTION_ORDER nedan håller platsen.
    ("proforma_skickad_kund",   "Fakturering",          "Proforma skickad – kund",      "datum", 200),
    ("faktura_adress",          "Fakturering",          "Faktura adress bekräftad",     "datum", 210),
    ("noc_skickad_kund",        "Fakturering",          "NOC skickad – kund",           "datum", 220),
    ("slutfaktura_skickad",     "Fakturering",          "Slutfaktura skickad – kund",   "datum", 230),
    ("slutfaktura_betald",      "Fakturering",          "Slutfaktura betald",           "datum", 240),
    ("reservdelskatalog",       "Dokumentation",        "Reservdelskatalog",            "datum", 250),
    ("luft_el_ritningar",       "Dokumentation",        "Luft- & elritningar",          "datum", 260),
    ("hemsida",                 "Dokumentation",        "Hemsida",                      "text",  270),
    ("coa_paskrift_kund",       "COA / framkomstintyg", "För påskrift – kund",          "datum", 280),
    ("coa_mail_ffb",            "COA / framkomstintyg", "Mail – FFB",                   "datum", 290),
]


def _seed_sales_milestones():
    """Lägger in saknade milstolpar. Idempotent – befintliga rader lämnas orörda
    så att kundens egna ändringar av etiketter och ordning överlever en omstart."""
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            for key, group_label, label, value_type, sort_order in SALES_MILESTONE_SEED:
                conn.execute(
                    text("""INSERT INTO sales_milestone_defs
                                (key, group_label, label, value_type, sort_order, is_active)
                            VALUES (:key, :grp, :label, :vt, :ord, TRUE)
                            ON CONFLICT (key) DO NOTHING"""),
                    {"key": key, "grp": group_label, "label": label, "vt": value_type, "ord": sort_order},
                )
            conn.commit()
    except Exception as e:
        print(f"Milestone seed warning: {e}")


_seed_sales_milestones()

app = FastAPI(title="Flow - Verkstadsystem", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(customers.router)
app.include_router(contacts.router)
app.include_router(vehicles.router)
app.include_router(articles.router)
app.include_router(work_orders.router)
app.include_router(phases.router)
app.include_router(purchases.router)
app.include_router(files.router)
app.include_router(activities.router)
app.include_router(tasks.router)
app.include_router(tasks.list_router)
app.include_router(notes.router)
app.include_router(time_entries.router)
app.include_router(dashboard.router)
app.include_router(settings.router)
app.include_router(pick_lists.router)
app.include_router(sales_leads.router)
app.include_router(sales_orders.router)
app.include_router(sales_milestones.router)
app.include_router(ffb_orders.router)


@app.on_event("startup")
def create_first_admin():
    db: Session = next(get_db())
    try:
        if db.query(models.User).count() == 0:
            admin = models.User(
                email=os.getenv("FIRST_ADMIN_EMAIL", "admin@flow.local"),
                hashed_password=hash_password(os.getenv("FIRST_ADMIN_PASSWORD", "admin")),
                full_name=os.getenv("FIRST_ADMIN_NAME", "Administratör"),
                role=models.UserRole.admin,
            )
            db.add(admin)
            db.commit()
            print(f"Admin-användare skapad: {admin.email}")
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"status": "ok"}
