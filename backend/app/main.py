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
    pick_lists,
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
