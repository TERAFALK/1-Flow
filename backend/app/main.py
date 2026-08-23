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
    pick_lists, sales_leads, sales_orders, sales_milestones,
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
SALES_MILESTONE_SEED = [
    # (key, group_label, label, value_type)
    ("orderbekraftelse",        "Order & betalning",    "Orderbekräftelse",            "datum"),
    ("bankpapper",              "Order & betalning",    "Bankpapper",                  "text"),
    ("faktura_10",              "Order & betalning",    "Faktura 10 %",                "datum"),
    ("faktura_10_betald",       "Order & betalning",    "Faktura 10 % betald",         "datum"),
    ("order_signerad",          "Order & betalning",    "Order signerad",              "datum"),
    ("fo_nr",                   "Order & betalning",    "FO-nr",                       "text"),
    ("chassi_info",             "Ritningar",            "Chassi info",                 "datum"),
    ("ritning_komplett",        "Ritningar",            "Komplett ritning med chassi", "datum"),
    ("lack_forslag_kund",       "Lackering",            "Förslag – kund",              "datum"),
    ("lack_forslag_ffb",        "Lackering",            "Förslag – FFB",               "datum"),
    ("lack_slutlig_kund",       "Lackering",            "Slutlig – kund",              "datum"),
    ("lack_slutlig_ffb",        "Lackering",            "Slutlig – FFB",               "datum"),
    ("agare_fordon",            "Registrering",         "Ägare / fordon",              "text"),
    ("ursprungskontroll",       "Registrering",         "Ursprungskontroll ansökan",   "datum"),
    ("ursprung_paskrift_kund",  "Registrering",         "För påskrift av kund",        "datum"),
    ("ursprung_postad_ts",      "Registrering",         "Postad till TS",              "datum"),
    ("aoc_nr",                  "AOC",                  "AOC-nr",                      "text"),
    ("aoc_skickad_kund",        "AOC",                  "Skickad – kund",              "text"),
    ("aoc_mailat_ffb",          "AOC",                  "Mailat – FFB",                "text"),
    ("aoc_kostnad_eur",         "AOC",                  "Kostnad EUR",                 "text"),
    ("proforma_skickad_kund",   "Fakturering",          "Proforma skickad – kund",     "datum"),
    ("faktura_adress",          "Fakturering",          "Faktura adress bekräftad",    "datum"),
    ("noc_skickad_kund",        "Fakturering",          "NOC skickad – kund",          "datum"),
    ("slutfaktura_skickad",     "Fakturering",          "Slutfaktura skickad – kund",  "datum"),
    ("slutfaktura_betald",      "Fakturering",          "Slutfaktura betald",          "datum"),
    ("reservdelskatalog",       "Dokumentation",        "Reservdelskatalog",           "datum"),
    ("luft_el_ritningar",       "Dokumentation",        "Luft- & elritningar",         "datum"),
    ("hemsida",                 "Dokumentation",        "Hemsida",                     "text"),
    ("coa_paskrift_kund",       "COA / framkomstintyg", "För påskrift – kund",         "datum"),
    ("coa_mail_ffb",            "COA / framkomstintyg", "Mail – FFB",                  "datum"),
]


def _seed_sales_milestones():
    """Lägger in saknade milstolpar. Idempotent – befintliga rader lämnas orörda
    så att kundens egna ändringar av etiketter och ordning överlever en omstart."""
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            for i, (key, group_label, label, value_type) in enumerate(SALES_MILESTONE_SEED):
                conn.execute(
                    text("""INSERT INTO sales_milestone_defs
                                (key, group_label, label, value_type, sort_order, is_active)
                            VALUES (:key, :grp, :label, :vt, :ord, TRUE)
                            ON CONFLICT (key) DO NOTHING"""),
                    {"key": key, "grp": group_label, "label": label, "vt": value_type, "ord": i * 10},
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
app.include_router(time_entries.router)
app.include_router(dashboard.router)
app.include_router(settings.router)
app.include_router(pick_lists.router)
app.include_router(sales_leads.router)
app.include_router(sales_orders.router)
app.include_router(sales_milestones.router)


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
