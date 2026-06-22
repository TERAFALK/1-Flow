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
)

models.Base.metadata.create_all(bind=engine)

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
