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
    # Behövs på FFB-beställningen till Feldbinder, som är på engelska och
    # kräver kundens VAT-nummer, land och kundnummer hos FFB
    vat_number = Column(String)
    country = Column(String)
    ffb_customer_number = Column(String)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    vehicles = relationship("Vehicle", back_populates="customer")
    work_orders = relationship("WorkOrder", back_populates="customer")
    contacts = relationship("ContactPerson", back_populates="customer", cascade="all, delete-orphan")
    # Ingen delete-cascade: en kund med affärer ska inte gå att radera (se customers.py)
    sales_leads = relationship("SalesLead", back_populates="customer")
    sales_orders = relationship("SalesOrder", back_populates="customer")
    # Följer med när kunden raderas – det är anteckningar, inte affärsposter
    tasks = relationship("Task", back_populates="customer", cascade="all, delete-orphan")
    crm_notes = relationship(
        "SalesLeadNote", back_populates="customer",
        cascade="all, delete-orphan", order_by="SalesLeadNote.note_date.desc()",
    )


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
    """Uppgift på en arbetsorder, en offert eller en kund. En offerts uppgifter
    flyttas över till arbetsordern när affären blir såld."""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"))
    lead_id = Column(Integer, ForeignKey("sales_leads.id"))
    customer_id = Column(Integer, ForeignKey("customers.id"))
    title = Column(String, nullable=False)
    description = Column(Text)
    assigned_to = Column(Integer, ForeignKey("users.id"))
    due_date = Column(DateTime)
    completed = Column(Boolean, default=False)
    completed_at = Column(DateTime)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    work_order = relationship("WorkOrder", back_populates="tasks")
    lead = relationship("SalesLead", back_populates="tasks")
    customer = relationship("Customer", back_populates="tasks")
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


class SalesLeadKind(str, PyEnum):
    # OBS: SQLAlchemy lagrar medlemmens NAMN i Postgres-enumen `salesleadkind`,
    # så nya medlemmar kräver ALTER TYPE-migration i main.py.
    feldbinder = "feldbinder"   # tankpåbyggnader via FFB – hela milstolpskedjan
    verkstad = "verkstad"       # offerter på verkstadsjobb – blir en arbetsorder


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
    # Vilken affärstyp förfrågan hör till. Fälten nedan som rör FFB används bara
    # av feldbinder-förfrågningar; verkstadsofferter lämnar dem tomma.
    kind = Column(
        Enum(SalesLeadKind), default=SalesLeadKind.feldbinder, nullable=False, index=True
    )
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
    description = Column(Text)                            # vad förfrågan gäller
    notes = Column(Text)                                  # interna anteckningar
    # En verkstadsoffert blir en arbetsorder när den säljs, inte en SalesOrder
    work_order_id = Column(Integer, ForeignKey("work_orders.id"))
    archived_at = Column(DateTime, index=True)

    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = relationship("Customer", back_populates="sales_leads")
    contact_person = relationship("ContactPerson")
    work_order = relationship("WorkOrder")
    assignee = relationship("User", foreign_keys=[assigned_to])
    creator = relationship("User", foreign_keys=[created_by])
    lead_notes = relationship(
        "SalesLeadNote", back_populates="lead",
        cascade="all, delete-orphan", order_by="SalesLeadNote.note_date.desc()",
    )
    files = relationship("SalesLeadFile", back_populates="lead", cascade="all, delete-orphan")
    ffb_quote = relationship(
        "FfbQuote", back_populates="lead", uselist=False, cascade="all, delete-orphan"
    )
    activities = relationship(
        "SalesActivity", back_populates="lead", cascade="all, delete-orphan",
        order_by="SalesActivity.sort_order",
    )
    tasks = relationship(
        "Task", back_populates="lead", cascade="all, delete-orphan", order_by="Task.id",
    )


class SalesLeadNote(Base):
    """En post i uppföljningsloggen. I Excel låg allt detta hopklistrat i en cell.

    Hänger på en förfrågan, en såld order eller en kund. Uppföljningen ska kunna
    fortsätta efter att affären gått igenom, och en kundkontakt som inte är en
    affär ska kunna loggas ändå. Tabellnamnet är kvar från när bara förfrågningar
    hade logg."""
    __tablename__ = "sales_lead_notes"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("sales_leads.id"))
    order_id = Column(Integer, ForeignKey("sales_orders.id"))
    customer_id = Column(Integer, ForeignKey("customers.id"))
    note_date = Column(Date, nullable=False)
    kind = Column(Enum(SalesNoteKind), default=SalesNoteKind.anteckning, nullable=False)
    body = Column(Text, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    lead = relationship("SalesLead", back_populates="lead_notes")
    order = relationship("SalesOrder", back_populates="order_notes")
    customer = relationship("Customer", back_populates="crm_notes")
    creator = relationship("User")
    files = relationship(
        "SalesLeadFile", back_populates="note",
        cascade="all, delete-orphan", order_by="SalesLeadFile.id",
    )


class SalesActivity(Base):
    """Egen aktivitet i Gantt-schemat, på en förfrågan eller en order. Speglar
    WorkOrderPhase men med rena datum – säljprocessen räknas i dagar, inte timmar."""
    __tablename__ = "sales_activities"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("sales_leads.id"))
    order_id = Column(Integer, ForeignKey("sales_orders.id"))
    name = Column(String, nullable=False)
    color = Column(String, default="#E2001A")
    start_date = Column(Date)
    end_date = Column(Date)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    lead = relationship("SalesLead", back_populates="activities")
    order = relationship("SalesOrder", back_populates="activities")


class SalesLeadFile(Base):
    """Bilaga i säljdelen. Hänger på antingen en förfrågan (offert-PDF och annat
    underlag) eller på en enskild anteckning – ett mail eller några kort som kom
    in i samband med kontakten."""
    __tablename__ = "sales_lead_files"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("sales_leads.id"))
    note_id = Column(Integer, ForeignKey("sales_lead_notes.id"))
    # Sätts på filer Flow själv genererar (offertförfrågan till FFB) så att de
    # går att hitta och ersätta utan att gissa på originalnamnet
    group_label = Column(String, index=True)
    filename = Column(String, nullable=False)             # uuid-namnet på disk
    original_name = Column(String, nullable=False)
    mime_type = Column(String)
    size_bytes = Column(BigInteger)
    uploaded_by = Column(Integer, ForeignKey("users.id"))
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    lead = relationship("SalesLead", back_populates="files")
    note = relationship("SalesLeadNote", back_populates="files")
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
    # Avslutade ordrar arkiveras istället för att raderas – de behövs i provisionen
    archived_at = Column(DateTime, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = relationship("Customer", back_populates="sales_orders")
    lead = relationship("SalesLead")
    milestones = relationship(
        "SalesOrderMilestone", back_populates="order", cascade="all, delete-orphan"
    )
    aocs = relationship(
        "SalesOrderAoc", back_populates="order",
        cascade="all, delete-orphan", order_by="SalesOrderAoc.sort_order",
    )
    files = relationship(
        "SalesOrderFile", back_populates="order", cascade="all, delete-orphan"
    )
    order_notes = relationship(
        "SalesLeadNote", back_populates="order", cascade="all, delete-orphan",
        order_by="SalesLeadNote.note_date.desc()",
    )
    activities = relationship(
        "SalesActivity", back_populates="order", cascade="all, delete-orphan",
        order_by="SalesActivity.sort_order",
    )
    ffb_order = relationship(
        "FfbOrder", back_populates="order", uselist=False, cascade="all, delete-orphan"
    )


class SalesOrderAoc(Base):
    """Ett AOC-intyg. En order kan ha flera (NB001, NB002, NB003…), vilket i Excel
    löstes genom att trycka in flera värden i samma cell ("NB002    NB003")."""
    __tablename__ = "sales_order_aocs"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("sales_orders.id"), nullable=False)
    aoc_number = Column(String)                           # NB001
    sent_customer = Column(Date)                          # skickad – kund
    mailed_ffb = Column(Date)                             # mailat – FFB
    cost_eur = Column(Numeric(12, 2))                     # kostnad EUR
    notes = Column(Text)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    order = relationship("SalesOrder", back_populates="aocs")
    files = relationship(
        "SalesOrderFile", back_populates="aoc", cascade="all, delete-orphan"
    )


class SalesOrderFile(Base):
    """Bilaga på en såld order. Antingen hör den till ett avsnitt (group_label,
    t.ex. "Lackering") eller till ett enskilt AOC-intyg (aoc_id). Är båda tomma är
    det en allmän orderbilaga.

    group_label är etiketten från sales_milestone_defs och inte en nyckel – döps
    ett avsnitt om via Inställningar hamnar äldre filer under det gamla namnet."""
    __tablename__ = "sales_order_files"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("sales_orders.id"), nullable=False)
    group_label = Column(String, index=True)
    aoc_id = Column(Integer, ForeignKey("sales_order_aocs.id"))
    filename = Column(String, nullable=False)             # uuid-namnet på disk
    original_name = Column(String, nullable=False)
    mime_type = Column(String)
    size_bytes = Column(BigInteger)
    uploaded_by = Column(Integer, ForeignKey("users.id"))
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    order = relationship("SalesOrder", back_populates="files")
    aoc = relationship("SalesOrderAoc", back_populates="files")
    uploader = relationship("User")


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


class FfbOrder(Base):
    """Beställningen som skickas vidare till Feldbinder när affären är såld.

    Motsvarar Word-mallen "FFB Order" som kunden fyllde i för hand. Raden skapas
    förifylld ur ordern, förfrågan och kunden första gången beställningen
    öppnas, och får sedan redigeras fritt – texten som går till FFB är kundens.

    Alla värden är text: mallens rutor innehåller "1 pc", "ASAP" och "Aug 2026"
    lika gärna som ett datum eller ett antal.
    """
    __tablename__ = "ffb_orders"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(
        Integer, ForeignKey("sales_orders.id"), nullable=False, unique=True, index=True
    )

    # Huvud
    doc_date = Column(Date)

    # Kundblocket lagras inte här. Namn, adress, VAT, land, telefon, mail och
    # kontaktperson hämtas ur kunden och förfrågan när beställningen läses, så
    # att en rättad adress slår igenom direkt i stället för att ligga kvar som
    # en kopia från den dag affären såldes.

    # Order info
    quantity = Column(String)
    quotation_number = Column(String)
    delivery_time = Column(String)
    product_type = Column(String)
    part_no = Column(String)
    part_delivery_time = Column(String)
    volume_approx = Column(String)
    transport_of = Column(String)
    country_of_registration = Column(String)
    drawing_number = Column(String)
    special_feature = Column(String)

    # Chassis info
    chassis_make = Column(String)
    wheel_base = Column(String)
    fo_number = Column(String)
    chassis_delivery_time = Column(String)

    # Villkor
    terms_payment = Column(String)
    terms_delivery = Column(String)

    order_text = Column(Text)

    updated_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    order = relationship("SalesOrder", back_populates="ffb_order")


class FfbQuote(Base):
    """Offertförfrågan till Feldbinder – mallen "Quotation Request".

    Samma dokument som beställningen fast ett steg tidigare: den skickas för att
    få ett pris, innan affären finns. Därför saknas antal, offertnummer och
    leveranstider – de är inte bestämda än.

    Bara feldbinder-förfrågningar har en; verkstadsofferter går aldrig via FFB.
    Kundblocket lagras inte utan hämtas ur kunden när posten läses.
    """
    __tablename__ = "ffb_quotes"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(
        Integer, ForeignKey("sales_leads.id"), nullable=False, unique=True, index=True
    )

    doc_date = Column(Date)

    # Quotation info
    product_type = Column(String)
    volume_approx = Column(String)
    transport_of = Column(String)
    country_of_registration = Column(String)
    drawing_number = Column(String)
    special_feature = Column(String)

    # Chassis info
    chassis_make = Column(String)
    wheel_base = Column(String)
    fo_number = Column(String)

    terms_payment = Column(String)
    terms_delivery = Column(String)

    request_text = Column(Text)

    # Svensk version av fritexten, till den svenska utskriften. Fylls av
    # översättningsknappen och får sedan rättas för hand – maskinöversatt
    # tankterminologi behöver läsas igenom innan dokumentet går vidare. Är de
    # tomma faller den svenska PDF:en tillbaka på originaltexten.
    request_text_sv = Column(Text)
    special_feature_sv = Column(String)

    updated_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    lead = relationship("SalesLead", back_populates="ffb_quote")


# ── Planeringsmöte ────────────────────────────────────────────────────────────
# Veckodokumentet som gås igenom fysiskt med verkstaden varje vecka. Ersätter en
# Word-fil som skrevs om från grunden varje gång, trots att jobben pågår över
# flera veckor och raderna därför till stor del är desamma.

# Frånvarotyper. Medvetet vanlig text och inte ett Postgres-enum: ett enum
# kräver ALTER TYPE för varje nytt värde, och de här är etiketter som mycket väl
# kan behöva utökas.
ABSENCE_KINDS = ("semester", "ledig", "sjuk", "annat")


class PlanningMeeting(Base):
    """Ett veckomöte. Nyckeln är ISO-året och ISO-veckan, inte kalenderåret:
    vecka 1 2027 börjar 2026-12-28, så meeting_date.year skulle ge fel vecka."""
    __tablename__ = "planning_meetings"
    __table_args__ = (UniqueConstraint("iso_year", "iso_week", name="uq_planning_week"),)

    id = Column(Integer, primary_key=True, index=True)
    monday_date = Column(Date, nullable=False)            # veckans ankare
    iso_year = Column(Integer, nullable=False, index=True)
    iso_week = Column(Integer, nullable=False)
    meeting_date = Column(Date)                           # mötet kan hållas fredagen innan

    notes = Column(Text)                                  # Noteringar//
    ffb_current = Column(Text)
    open_quotes = Column(Text)
    future_work = Column(Text)

    # Rubrikerna är data och inte konstanter – "Arbete under 2026/27" innehåller
    # ett årtal som måste gå att ändra utan att någon rör koden
    ffb_heading = Column(String, default="Aktuellt FFB")
    quotes_heading = Column(String, default="Pågående offerter")
    future_heading = Column(String, default="Arbete under 2026/27")

    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    days = relationship(
        "PlanningMeetingDay", back_populates="meeting",
        cascade="all, delete-orphan", order_by="PlanningMeetingDay.sort_order",
    )
    items = relationship(
        "PlanningMeetingItem", back_populates="meeting",
        cascade="all, delete-orphan", order_by="PlanningMeetingItem.sort_order",
    )


class PlanningMeetingDay(Base):
    """En rad i Mån–Fre-schemat. Bär ett riktigt datum och inte ett veckodagsnummer,
    så att frånvaro och planerade leveranser går att matcha utan att först räkna
    ut vilken måndag veckan avser."""
    __tablename__ = "planning_meeting_days"

    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(
        Integer, ForeignKey("planning_meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day_date = Column(Date, nullable=False)
    text = Column(Text)
    sort_order = Column(Integer, default=0)

    meeting = relationship("PlanningMeeting", back_populates="days")


class PlanningMeetingItem(Base):
    """En rad i tabellen "Pågående arbete/ej startat arbete".

    customer_text är en ögonblicksbild av kundnamnet. Kunden kan raderas, och
    raden ska ändå gå att läsa – samma grepp som artikelnumret på en orderrad.
    """
    __tablename__ = "planning_meeting_items"

    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(
        Integer, ForeignKey("planning_meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sort_order = Column(Integer, default=0)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="SET NULL"))
    customer_text = Column(String)
    work_order_id = Column(Integer, ForeignKey("work_orders.id", ondelete="SET NULL"), index=True)
    description = Column(Text)
    # Bockas av under mötet. Avbockade rader följer inte med till nästa vecka
    # och kommer inte med i utskriften.
    done = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    meeting = relationship("PlanningMeeting", back_populates="items")
    customer = relationship("Customer")
    work_order = relationship("WorkOrder")
    assignees = relationship(
        "PlanningItemAssignee", back_populates="item",
        cascade="all, delete-orphan", order_by="PlanningItemAssignee.sort_order",
    )


class PlanningItemAssignee(Base):
    """Ansvarig på en rad. Egen tabell och inte en lista med id:n i en JSON-kolumn:
    borttagning av en användare släpper nullbara referenser för hand (se
    routers/users.py), och en JSON-lista hade varit osynlig för den städningen."""
    __tablename__ = "planning_item_assignees"
    __table_args__ = (UniqueConstraint("item_id", "user_id", name="uq_planning_item_user"),)

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(
        Integer, ForeignKey("planning_meeting_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    sort_order = Column(Integer, default=0)

    item = relationship("PlanningMeetingItem", back_populates="assignees")
    user = relationship("User")


class UserAbsence(Base):
    """Frånvaro för en person. Används av veckovyn för att visa vilka som är
    borta, och för att kunna föreslå raden i Noteringar – aldrig för att skriva
    något automatiskt."""
    __tablename__ = "user_absences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=False, index=True)
    kind = Column(String, default="ledig")
    note = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
