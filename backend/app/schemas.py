from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from .models import (
    UserRole, WorkOrderStatus, TimeEntryType, StockTransactionType,
    PurchaseStatus, FileType, ActivityType,
)


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


# ── Users ─────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str
    role: UserRole = UserRole.tekniker


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


# ── Customers ─────────────────────────────────────────────────────────────────

class CustomerCreate(BaseModel):
    name: str
    org_number: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    notes: Optional[str] = None


class CustomerUpdate(CustomerCreate):
    name: Optional[str] = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    org_number: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    city: Optional[str]
    postal_code: Optional[str]
    notes: Optional[str]
    created_at: datetime


# ── Contact Persons ───────────────────────────────────────────────────────────

class ContactPersonCreate(BaseModel):
    name: str
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_primary: bool = False


class ContactPersonUpdate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_primary: Optional[bool] = None


class ContactPersonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_id: int
    name: str
    title: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    is_primary: bool
    created_at: datetime


# ── Vehicles ──────────────────────────────────────────────────────────────────

class VehicleCreate(BaseModel):
    customer_id: int
    license_plate: str
    vin: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    engine: Optional[str] = None
    gearbox: Optional[str] = None
    odometer: Optional[int] = None
    notes: Optional[str] = None


class VehicleUpdate(BaseModel):
    customer_id: Optional[int] = None
    license_plate: Optional[str] = None
    vin: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    engine: Optional[str] = None
    gearbox: Optional[str] = None
    odometer: Optional[int] = None
    notes: Optional[str] = None


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_id: int
    license_plate: str
    vin: Optional[str]
    make: Optional[str]
    model: Optional[str]
    year: Optional[int]
    engine: Optional[str]
    gearbox: Optional[str]
    odometer: Optional[int]
    notes: Optional[str]
    created_at: datetime
    customer: Optional[CustomerOut] = None


# ── Articles ──────────────────────────────────────────────────────────────────

class ArticleCreate(BaseModel):
    article_number: Optional[str] = None
    barcode: Optional[str] = None
    name: str
    description: Optional[str] = None
    supplier: Optional[str] = None
    unit: str = "st"
    price: Decimal = Decimal("0")
    stock_quantity: Decimal = Decimal("0")
    min_stock: Decimal = Decimal("0")
    location: Optional[str] = None


class ArticleUpdate(BaseModel):
    article_number: Optional[str] = None
    barcode: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    supplier: Optional[str] = None
    unit: Optional[str] = None
    price: Optional[Decimal] = None
    stock_quantity: Optional[Decimal] = None
    min_stock: Optional[Decimal] = None
    location: Optional[str] = None


class ArticleImportResult(BaseModel):
    imported: int
    seconds: float


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    article_number: Optional[str]
    barcode: Optional[str]
    name: str
    description: Optional[str]
    supplier: Optional[str]
    unit: str
    price: Decimal
    stock_quantity: Decimal
    min_stock: Decimal
    location: Optional[str]
    created_at: datetime


# ── Work Order Lines ──────────────────────────────────────────────────────────

class WorkOrderLineCreate(BaseModel):
    article_id: Optional[int] = None
    description: str
    quantity: Decimal = Decimal("1")
    unit: str = "st"
    unit_price: Decimal = Decimal("0")


class WorkOrderLineUpdate(BaseModel):
    description: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    unit_price: Optional[Decimal] = None


class WorkOrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    work_order_id: int
    article_id: Optional[int]
    description: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    created_at: datetime
    article: Optional[ArticleOut] = None


# ── Time Entries ──────────────────────────────────────────────────────────────

class TimeEntryCreate(BaseModel):
    work_order_id: int
    description: Optional[str] = None
    entry_type: TimeEntryType = TimeEntryType.övrigt


class TimeEntryStop(BaseModel):
    description: Optional[str] = None
    entry_type: Optional[TimeEntryType] = None


class TimeEntryManual(BaseModel):
    work_order_id: int
    start_time: datetime
    end_time: datetime
    entry_type: TimeEntryType = TimeEntryType.övrigt
    description: Optional[str] = None


class TimeEntryWorkOrderRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_number: str


class TimeEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    work_order_id: int
    user_id: int
    start_time: datetime
    end_time: Optional[datetime]
    duration_minutes: Optional[int]
    description: Optional[str]
    entry_type: TimeEntryType
    created_at: datetime
    user: Optional[UserOut] = None
    work_order: Optional[TimeEntryWorkOrderRef] = None


# ── Work Order Phases (Gantt) ─────────────────────────────────────────────────

class WorkOrderPhaseCreate(BaseModel):
    name: str
    color: str = "#E2001A"
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    sort_order: int = 0


class WorkOrderPhaseUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    sort_order: Optional[int] = None


class WorkOrderPhaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    work_order_id: int
    name: str
    color: str
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    sort_order: int
    created_at: datetime


# ── Purchases ─────────────────────────────────────────────────────────────────

class PurchaseLineCreate(BaseModel):
    article_id: Optional[int] = None
    description: str
    article_number: Optional[str] = None
    quantity: Decimal = Decimal("1")
    unit: str = "st"


class PurchaseLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    article_id: Optional[int]
    description: str
    article_number: Optional[str]
    quantity: Decimal
    unit: str


class PurchaseCreate(BaseModel):
    purchase_number: Optional[str] = None
    supplier: Optional[str] = None
    description: Optional[str] = None
    delivery_week: Optional[int] = None
    status: PurchaseStatus = PurchaseStatus.beställd
    lines: List[PurchaseLineCreate] = []


class PurchaseUpdate(BaseModel):
    purchase_number: Optional[str] = None
    supplier: Optional[str] = None
    description: Optional[str] = None
    delivery_week: Optional[int] = None
    status: Optional[PurchaseStatus] = None
    lines: Optional[List[PurchaseLineCreate]] = None


class PurchaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    work_order_id: int
    purchase_number: Optional[str]
    supplier: Optional[str]
    description: Optional[str]
    delivery_week: Optional[str]
    status: PurchaseStatus
    created_at: datetime
    lines: List[PurchaseLineOut] = []


# ── Files ─────────────────────────────────────────────────────────────────────

class WorkOrderFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    work_order_id: int
    filename: str
    original_name: str
    file_type: FileType
    mime_type: Optional[str]
    size_bytes: int
    uploaded_at: datetime
    uploaded_by: Optional[int]
    uploader: Optional[UserOut] = None


# ── Activities ────────────────────────────────────────────────────────────────

class ActivityCreate(BaseModel):
    activity_type: ActivityType = ActivityType.anteckning
    description: str


class ActivityUpdate(BaseModel):
    activity_type: Optional[ActivityType] = None
    description: Optional[str] = None


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    work_order_id: int
    activity_type: ActivityType
    description: str
    created_by: Optional[int]
    created_at: datetime
    creator: Optional[UserOut] = None


# ── Tasks ─────────────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    assigned_to: Optional[int] = None
    due_date: Optional[datetime] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assigned_to: Optional[int] = None
    due_date: Optional[datetime] = None
    completed: Optional[bool] = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    work_order_id: int
    title: str
    description: Optional[str]
    assigned_to: Optional[int]
    due_date: Optional[datetime]
    completed: bool
    completed_at: Optional[datetime]
    created_by: Optional[int]
    created_at: datetime
    assigned_user: Optional[UserOut] = None


# ── Work Orders ───────────────────────────────────────────────────────────────

class WorkOrderCreate(BaseModel):
    customer_id: int
    vehicle_id: Optional[int] = None
    description: str
    order_number: Optional[str] = None
    assigned_to: Optional[int] = None
    contact_person_id: Optional[int] = None
    scheduled_date: Optional[datetime] = None
    internal_notes: Optional[str] = None


class WorkOrderUpdate(BaseModel):
    customer_id: Optional[int] = None
    vehicle_id: Optional[int] = None
    description: Optional[str] = None
    body_text: Optional[str] = None
    status: Optional[WorkOrderStatus] = None
    assigned_to: Optional[int] = None
    contact_person_id: Optional[int] = None
    scheduled_date: Optional[datetime] = None
    internal_notes: Optional[str] = None


class WorkOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_number: str
    customer_id: int
    vehicle_id: Optional[int]
    description: str
    body_text: Optional[str]
    status: WorkOrderStatus
    assigned_to: Optional[int]
    contact_person_id: Optional[int]
    scheduled_date: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    internal_notes: Optional[str]
    created_at: datetime
    customer: Optional[CustomerOut] = None
    vehicle: Optional[VehicleOut] = None
    assigned_to_user: Optional[UserOut] = None
    contact_person: Optional[ContactPersonOut] = None
    lines: List[WorkOrderLineOut] = []
    time_entries: List[TimeEntryOut] = []


class WorkOrderListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_number: str
    customer_id: int
    vehicle_id: Optional[int]
    description: str
    status: WorkOrderStatus
    assigned_to: Optional[int]
    scheduled_date: Optional[datetime]
    created_at: datetime
    customer: Optional[CustomerOut] = None
    vehicle: Optional[VehicleOut] = None
    assigned_to_user: Optional[UserOut] = None


# ── Scanner ───────────────────────────────────────────────────────────────────

class ScanResult(BaseModel):
    article: Optional[ArticleOut] = None
    article_name: str
    line: WorkOrderLineOut
    stock_warning: bool
    stock_quantity: Optional[Decimal] = None
    unknown: bool = False


# ── Stock Transactions ────────────────────────────────────────────────────────

class StockTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    article_id: int
    quantity: Decimal
    transaction_type: StockTransactionType
    work_order_id: Optional[int]
    notes: Optional[str]
    created_at: datetime


# ── Settings ──────────────────────────────────────────────────────────────────

class SettingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    value: str


class SettingUpdate(BaseModel):
    value: str


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    total_open: int
    by_status: dict
    scheduled_today: int
    active_timers: int
    recent_orders: List[WorkOrderListItem]


# ── Pick lists ────────────────────────────────────────────────────────────────

class PickListLineCreate(BaseModel):
    article_id: Optional[int] = None
    description: str
    quantity: Decimal = Decimal("1")
    unit: str = "st"
    location: Optional[str] = None


class PickListLineUpdate(BaseModel):
    quantity: Optional[Decimal] = None
    picked: Optional[bool] = None


class PickListLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    article_id: Optional[int]
    description: str
    quantity: Decimal
    unit: str
    location: Optional[str]
    picked: bool
    article_number: Optional[str] = None

    @classmethod
    def from_line(cls, line):
        return cls(
            id=line.id,
            article_id=line.article_id,
            description=line.description,
            quantity=line.quantity,
            unit=line.unit,
            location=line.location,
            picked=line.picked,
            article_number=line.article.article_number if line.article else None,
        )


class PickListCreate(BaseModel):
    title: str
    notes: Optional[str] = None
    lines: List[PickListLineCreate] = []


class PickListUpdate(BaseModel):
    title: Optional[str] = None
    notes: Optional[str] = None


class PickListListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    notes: Optional[str]
    created_at: datetime
    line_count: int = 0


class PickListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    notes: Optional[str]
    created_at: datetime
    lines: List[PickListLineOut]


Token.model_rebuild()
