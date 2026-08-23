from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import (
    Column, Integer, String, DateTime, Date, ForeignKey,
    Numeric, Text, Boolean, Enum, BigInteger, Float, JSON,
    UniqueConstraint
)
from sqlalchemy.orm import relationship
from .database import Base


class UserRole(str, PyEnum):
    admin = "admin"
    tekniker = "tekniker"


class WorkOrderStatus(str, PyEnum):
    ny = "ny"
    planerad = "planerad"
    pagaende = "pagaende"
    klar = "klar"
    fakturerad = "fakturerad"


class TimeEntryType(str, PyEnum):
    felsökning = "felsökning"
    reparation = "reparation"
    provkörning = "provkörning"
    övrigt = "övrigt"


class StockTransactionType(str, PyEnum):
    in_ = "in"
    out = "out"
    justering = "justering"


class PurchaseStatus(str, PyEnum):
    # OBS: SQLAlchemy lagrar medlemmens NAMN i Postgres-enumen `purchasestatus`,
    # så nya medlemmar kräver ALTER TYPE-migration i main.py
    ej_beställd = "ej beställd"
    beställd = "beställd"
    inlevererad = "inlevererad"
    avbeställd = "avbeställd"


class FileType(str, PyEnum):
    document = "document"
    photo = "photo"
    drawing = "drawing"


class ActivityType(str, PyEnum):
    samtal = "samtal"
    händelse = "händelse"
    anteckning = "anteckning"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.tekniker, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    time_entries = relationship("TimeEntry", back_populates="user")
    assigned_orders = relationship(
        "WorkOrder", back_populates="assigned_to_user",
        foreign_keys="WorkOrder.assigned_to"
    )
    tasks = relationship("Task", back_populates="assigned_user", foreign_keys="Task.assigned_to")


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    org_number = Column(String)
    email = Column(String)
    phone = Column(String)
    address = Column(String)
    city = Column(String)
    postal_code = Column(String)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    vehicles = relationship("Vehicle", back_populates="customer")
    work_orders = relationship("WorkOrder", back_populates="customer")
    contacts = relationship("ContactPerson", back_populates="customer", cascade="all, delete-orphan")
    # Ingen delete-cascade: en kund med affärer ska inte gå att radera (se customers.py)
    sales_leads = relationship("SalesLead", back_populates="customer")
    sales_orders = relationship("SalesOrder", back_populates="customer")


class ContactPerson(Base):
    __tablename__ = "contact_persons"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    name = Column(String, nullable=False)
    title = Column(String)
    phone = Column(String)
    email = Column(String)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="contacts")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    license_plate = Column(String, nullable=False, index=True)
    vin = Column(String)
    make = Column(String)
    model = Column(String)
    year = Column(Integer)
    engine = Column(String)
    gearbox = Column(String)
    odometer = Column(Integer)
    kraftuttag = Column(String)
    utvaxling = Column(String)
    rotation = Column(String)
    medbringare = Column(String)
    # Mått för svängradieberäkning (mm resp. grader)
    wheelbase_mm = Column(Integer)
    width_mm = Column(Integer)
    front_overhang_mm = Column(Integer)
    rear_overhang_mm = Column(Integer)
    max_steering_angle = Column(Float)
    # Axelkonfiguration: [{"offset_mm": int, "steered": bool}, ...] (främre axel offset 0)
    axles = Column(JSON)
    # Sparad indata för axeltryck/tankplacering (fritt dict, se axleload.compute)
    axle_load = Column(JSON)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="vehicles")
    work_orders = relationship("WorkOrder", back_populates="vehicle")


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String, unique=True, nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"))
    description = Column(Text, nullable=False)
    body_text = Column(Text)
    status = Column(Enum(WorkOrderStatus), default=WorkOrderStatus.ny, nullable=False)
    assigned_to = Column(Integer, ForeignKey("users.id"))
    contact_person_id = Column(Integer, ForeignKey("contact_persons.id", ondelete="SET NULL"))
    scheduled_date = Column(DateTime)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    internal_notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer, ForeignKey("users.id"))

    customer = relationship("Customer", back_populates="work_orders")
    vehicle = relationship("Vehicle", back_populates="work_orders")
    contact_person = relationship("ContactPerson", foreign_keys=[contact_person_id])
    assigned_to_user = relationship(
        "User", back_populates="assigned_orders",
        foreign_keys=[assigned_to]
    )
    creator = relationship("User", foreign_keys=[created_by])
    lines = relationship(
        "WorkOrderLine", back_populates="work_order",
        cascade="all, delete-orphan", order_by="WorkOrderLine.id"
    )
    time_entries = relationship(
        "TimeEntry", back_populates="work_order",
        cascade="all, delete-orphan", order_by="TimeEntry.start_time"
    )
    phases = relationship(
        "WorkOrderPhase", back_populates="work_order",
        cascade="all, delete-orphan", order_by="WorkOrderPhase.sort_order"
    )
    purchases = relationship(
        "Purchase", back_populates="work_order",
        cascade="all, delete-orphan", order_by="Purchase.id"
    )
    files = relationship(
        "WorkOrderFile", back_populates="work_order",
        cascade="all, delete-orphan", order_by="WorkOrderFile.uploaded_at"
    )
    activities = relationship(
        "Activity", back_populates="work_order",
        cascade="all, delete-orphan", order_by="Activity.created_at.desc()"
    )
    tasks = relationship(
        "Task", back_populates="work_order",
        cascade="all, delete-orphan", order_by="Task.id"
    )


class WorkOrderPhase(Base):
    __tablename__ = "work_order_phases"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False)
    name = Column(String, nullable=False)
    color = Column(String, default="#E2001A")
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    work_order = relationship("WorkOrder", back_populates="phases")


class Purchase(Base):
    __tablename__ = "purchases"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False)
    purchase_number = Column(String)
    supplier = Column(String)
    description = Column(String)
    article_number = Column(String)
    quantity = Column(Numeric(10, 2), default=1)
    delivery_week = Column(String)
    status = Column(Enum(PurchaseStatus), default=PurchaseStatus.beställd)
    created_at = Column(DateTime, default=datetime.utcnow)

    work_order = relationship("WorkOrder", back_populates="purchases")
    lines = relationship(
        "PurchaseLine", back_populates="purchase",
        cascade="all, delete-orphan", order_by="PurchaseLine.id"
    )


class PurchaseLine(Base):
    __tablename__ = "purchase_lines"

    id = Column(Integer, primary_key=True, index=True)
    purchase_id = Column(Integer, ForeignKey("purchases.id"), nullable=False)
    article_id = Column(Integer, ForeignKey("articles.id"))
    description = Column(String, nullable=False)
    article_number = Column(String)
    quantity = Column(Numeric(10, 2), default=1, nullable=False)
    unit = Column(String, default="st")

    purchase = relationship("Purchase", back_populates="lines")
    article = relationship("Article")


class WorkOrderFile(Base):
    __tablename__ = "work_order_files"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False)
    filename = Column(String, nullable=False)
    original_name = Column(String, nullable=False)
    file_type = Column(Enum(FileType), nullable=False)
    mime_type = Column(String)
    size_bytes = Column(BigInteger, default=0)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    uploaded_by = Column(Integer, ForeignKey("users.id"))

    work_order = relationship("WorkOrder", back_populates="files")
    uploader = relationship("User", foreign_keys=[uploaded_by])


class Activity(Base):
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False)
    activity_type = Column(Enum(ActivityType), default=ActivityType.anteckning, nullable=False)
    description = Column(Text, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    work_order = relationship("WorkOrder", back_populates="activities")
    creator = relationship("User", foreign_keys=[created_by])


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    assigned_to = Column(Integer, ForeignKey("users.id"))
    due_date = Column(DateTime)
    completed = Column(Boolean, default=False)
    completed_at = Column(DateTime)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    work_order = relationship("WorkOrder", back_populates="tasks")
    assigned_user = relationship("User", back_populates="tasks", foreign_keys=[assigned_to])
    creator = relationship("User", foreign_keys=[created_by])


class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    article_number = Column(String, index=True)
    barcode = Column(String, index=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    supplier = Column(String)
    unit = Column(String, default="st")
    price = Column(Numeric(10, 2), default=0)
    stock_quantity = Column(Numeric(10, 2), default=0)
    min_stock = Column(Numeric(10, 2), default=0)
    location = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    work_order_lines = relationship("WorkOrderLine", back_populates="article")
    stock_transactions = relationship("StockTransaction", back_populates="article")


class WorkOrderLine(Base):
    __tablename__ = "work_order_lines"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False)
    article_id = Column(Integer, ForeignKey("articles.id"))
    # Artikelnumret sparas på raden (inte bara via article_id) så att det överlever
    # en tömning/ominläsning av artikelregistret – se articles._wipe_articles
    article_number = Column(String, index=True)
    description = Column(String, nullable=False)
    quantity = Column(Numeric(10, 2), default=1, nullable=False)
    unit = Column(String, default="st")
    unit_price = Column(Numeric(10, 2), default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    work_order = relationship("WorkOrder", back_populates="lines")
    article = relationship("Article", back_populates="work_order_lines")


class TimeEntry(Base):
    __tablename__ = "time_entries"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime)
    duration_minutes = Column(Integer)
    description = Column(String)
    entry_type = Column(Enum(TimeEntryType), default=TimeEntryType.övrigt)
    created_at = Column(DateTime, default=datetime.utcnow)

    work_order = relationship("WorkOrder", back_populates="time_entries")
    user = relationship("User", back_populates="time_entries")


class StockTransaction(Base):
    __tablename__ = "stock_transactions"

    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    quantity = Column(Numeric(10, 2), nullable=False)
    transaction_type = Column(Enum(StockTransactionType), nullable=False)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    notes = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    article = relationship("Article", back_populates="stock_transactions")


class Settings(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)


class PickList(Base):
    __tablename__ = "pick_lists"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    notes = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    creator = relationship("User")
    lines = relationship("PickListLine", back_populates="pick_list", cascade="all, delete-orphan")


class PickListLine(Base):
    __tablename__ = "pick_list_lines"

    id = Column(Integer, primary_key=True, index=True)
    pick_list_id = Column(Integer, ForeignKey("pick_lists.id"), nullable=False)
    article_id = Column(Integer, ForeignKey("articles.id"))
    # Se WorkOrderLine.article_number – bevaras vid ominläsning av artikelregistret
    article_number = Column(String, index=True)
    description = Column(String, nullable=False)
    quantity = Column(Numeric(10, 2), default=1, nullable=False)
    unit = Column(String, default="st")
    location = Column(String)
    picked = Column(Boolean, default=False)

    pick_list = relationship("PickList", back_populates="lines")
    article = relationship("Article")


# ── Försäljning / CRM ─────────────────────────────────────────────────────────
# Ersätter kundens Excel-fil "Arbetande offerter FFB SBT, försäljning.xlsx" som
# innehåller två processer: offertförfrågningar (SalesLead) och uppföljning av
# sålda affärer med ~30 milstolpar per order (SalesOrder + SalesOrderMilestone).


class SalesLeadStatus(str, PyEnum):
    # OBS: SQLAlchemy lagrar medlemmens NAMN i Postgres-enumen `salesleadstatus`,
    # så nya medlemmar kräver ALTER TYPE-migration i main.py. Namnen hålls ASCII
    # (sald) – etiketten "Såld" sätts i frontend.
    ny = "ny"
    skickad = "skickad"
    jobbar = "jobbar"
    sald = "sald"
    avslutad = "avslutad"


class SalesNoteKind(str, PyEnum):
    samtal = "samtal"
    mail = "mail"
    mote = "mote"
    anteckning = "anteckning"


class MilestoneValueType(str, PyEnum):
    datum = "datum"
    text = "text"
    ja_nej = "ja_nej"


class SalesLead(Base):
    """En offertförfrågan – motsvarar en rad i Excel-fliken "Offertförfrågan Lista"."""
    __tablename__ = "sales_leads"

    id = Column(Integer, primary_key=True, index=True)
    activity_number = Column(String, index=True)          # Aktivitet (HubSpot-nr)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    contact_person_id = Column(Integer, ForeignKey("contact_persons.id"))
    product_type = Column(String)                         # Objekt – KIA/AUF/HEUT/...
    size = Column(String)                                 # Storlek – t.ex. 45,3
    quantity = Column(Integer, default=1)
    status = Column(Enum(SalesLeadStatus), default=SalesLeadStatus.ny, nullable=False, index=True)

    date_request = Column(Date)                           # Datum Förfrågan
    date_sent_ffb = Column(Date)                          # Datum skickat FFB
    date_back_ffb = Column(Date)                          # Datum tillbaka FFB
    date_sent_customer = Column(Date)                     # Datum skickat kund

    quote_number = Column(String, index=True)             # offert nr, t.ex. N11068496
    estimated_value = Column(Numeric(12, 2))
    currency = Column(String, default="EUR")
    next_followup_date = Column(Date, index=True)
    assigned_to = Column(Integer, ForeignKey("users.id"))
    external_link = Column(String)                        # Offert Länk – gammal UNC-sökväg
    lost_reason = Column(String)
    notes = Column(Text)

    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = relationship("Customer", back_populates="sales_leads")
    contact_person = relationship("ContactPerson")
    assignee = relationship("User", foreign_keys=[assigned_to])
    creator = relationship("User", foreign_keys=[created_by])
    lead_notes = relationship(
        "SalesLeadNote", back_populates="lead",
        cascade="all, delete-orphan", order_by="SalesLeadNote.note_date.desc()",
    )
    files = relationship("SalesLeadFile", back_populates="lead", cascade="all, delete-orphan")


class SalesLeadNote(Base):
    """En post i uppföljningsloggen. I Excel låg allt detta hopklistrat i en cell."""
    __tablename__ = "sales_lead_notes"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("sales_leads.id"), nullable=False)
    note_date = Column(Date, nullable=False)
    kind = Column(Enum(SalesNoteKind), default=SalesNoteKind.anteckning, nullable=False)
    body = Column(Text, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    lead = relationship("SalesLead", back_populates="lead_notes")
    creator = relationship("User")


class SalesLeadFile(Base):
    """Offert-PDF och annat underlag. Speglar WorkOrderFile men mot förfrågningar."""
    __tablename__ = "sales_lead_files"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("sales_leads.id"), nullable=False)
    filename = Column(String, nullable=False)             # uuid-namnet på disk
    original_name = Column(String, nullable=False)
    mime_type = Column(String)
    size_bytes = Column(BigInteger)
    uploaded_by = Column(Integer, ForeignKey("users.id"))
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    lead = relationship("SalesLead", back_populates="files")
    uploader = relationship("User")


class SalesOrder(Base):
    """En såld affär – motsvarar en rad i Excel-årsflikarna. Året härleds ur sold_date."""
    __tablename__ = "sales_orders"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("sales_leads.id"))
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    order_number = Column(String, index=True)             # order – N071010
    serial_number = Column(String)                        # tillverkningsnr / VIN
    product_type = Column(String)                         # typ – KIA28
    price = Column(Numeric(12, 2))
    currency = Column(String, default="EUR")
    commission = Column(Numeric(12, 2))                   # provision
    commission_paid_date = Column(Date)                   # utbet
    sold_date = Column(Date, index=True)                  # datum såld
    delivery_date = Column(Date)                          # lev kund
    planned_delivery = Column(Date)                       # pl lev
    delivery_week = Column(String)                        # v
    registration_number = Column(String)                  # reg nr
    weight_kg = Column(Integer)                           # vikt
    visit_ffb = Column(Boolean, default=False)            # besök
    sort_index = Column(Integer)                          # löpnumret i kolumn A
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = relationship("Customer", back_populates="sales_orders")
    lead = relationship("SalesLead")
    milestones = relationship(
        "SalesOrderMilestone", back_populates="order", cascade="all, delete-orphan"
    )


class SalesMilestoneDef(Base):
    """Mallen för milstolparna. Kolumnuppsättningen i Excel har ändrats varje år
    (10 st 2013, 50 st 2018), därför är stegen data och inte kolumner."""
    __tablename__ = "sales_milestone_defs"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False)
    group_label = Column(String, nullable=False)
    label = Column(String, nullable=False)
    value_type = Column(Enum(MilestoneValueType), default=MilestoneValueType.datum, nullable=False)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)


class SalesOrderMilestone(Base):
    """Ifyllt värde för en milstolpe. value_text finns eftersom flera Excel-celler
    innehåller fritext ("x", "NB001 NB002", "Finns ej enl FFB") och inte datum."""
    __tablename__ = "sales_order_milestones"
    __table_args__ = (UniqueConstraint("order_id", "def_id", name="uq_order_milestone"),)

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("sales_orders.id"), nullable=False)
    def_id = Column(Integer, ForeignKey("sales_milestone_defs.id"), nullable=False)
    value_date = Column(Date)
    value_text = Column(String)
    completed = Column(Boolean, default=False)
    updated_by = Column(Integer, ForeignKey("users.id"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    order = relationship("SalesOrder", back_populates="milestones")
    definition = relationship("SalesMilestoneDef")
