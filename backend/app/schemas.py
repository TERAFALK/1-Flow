from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from .models import (
    UserRole, WorkOrderStatus, TimeEntryType, StockTransactionType,
    PurchaseStatus, FileType, ActivityType,
    SalesLeadStatus, SalesLeadKind, SalesNoteKind, MilestoneValueType,
)


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class TechnicianOption(BaseModel):
    """Publik teknikerlista för inloggningsväljaren – avsiktligt bara id och namn."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str


class TechnicianLoginRequest(BaseModel):
    user_id: int
    password: str


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
    vat_number: Optional[str] = None
    country: Optional[str] = None
    ffb_customer_number: Optional[str] = None
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
    vat_number: Optional[str] = None
    country: Optional[str] = None
    ffb_customer_number: Optional[str] = None
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

class AxleSpec(BaseModel):
    offset_mm: int          # avstånd bakom främre axeln (främre axeln = 0)
    steered: bool = False


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
    kraftuttag: Optional[str] = None
    utvaxling: Optional[str] = None
    rotation: Optional[str] = None
    medbringare: Optional[str] = None
    wheelbase_mm: Optional[int] = None
    width_mm: Optional[int] = None
    front_overhang_mm: Optional[int] = None
    rear_overhang_mm: Optional[int] = None
    max_steering_angle: Optional[float] = None
    axles: Optional[List[AxleSpec]] = None
    axle_load: Optional[dict] = None
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
    kraftuttag: Optional[str] = None
    utvaxling: Optional[str] = None
    rotation: Optional[str] = None
    medbringare: Optional[str] = None
    wheelbase_mm: Optional[int] = None
    width_mm: Optional[int] = None
    front_overhang_mm: Optional[int] = None
    rear_overhang_mm: Optional[int] = None
    max_steering_angle: Optional[float] = None
    axles: Optional[List[AxleSpec]] = None
    axle_load: Optional[dict] = None
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
    kraftuttag: Optional[str] = None
    utvaxling: Optional[str] = None
    rotation: Optional[str] = None
    medbringare: Optional[str] = None
    wheelbase_mm: Optional[int] = None
    width_mm: Optional[int] = None
    front_overhang_mm: Optional[int] = None
    rear_overhang_mm: Optional[int] = None
    max_steering_angle: Optional[float] = None
    axles: Optional[List[AxleSpec]] = None
    axle_load: Optional[dict] = None
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
    relinked: int = 0


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
    article_number: Optional[str] = None
    description: str
    quantity: Decimal = Decimal("1")
    unit: str = "st"
    unit_price: Decimal = Decimal("0")


class WorkOrderLineBulkCreate(BaseModel):
    lines: List[WorkOrderLineCreate] = []


class WorkOrderLineUpdate(BaseModel):
    description: Optional[str] = None
    article_number: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    unit_price: Optional[Decimal] = None


class WorkOrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    work_order_id: int
    article_id: Optional[int]
    article_number: Optional[str] = None
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
    # Uppgiften hänger på en arbetsorder, en offert eller en kund
    work_order_id: Optional[int] = None
    lead_id: Optional[int] = None
    customer_id: Optional[int] = None
    title: str
    description: Optional[str]
    assigned_to: Optional[int]
    due_date: Optional[datetime]
    completed: bool
    completed_at: Optional[datetime]
    created_by: Optional[int]
    created_at: datetime
    assigned_user: Optional[UserOut] = None


class TaskListItem(TaskOut):
    """Uppgift i den globala listan. Bär med sig var den hör hemma så att listan
    kan visa källan och länka dit utan ett anrop per rad."""
    parent_type: str = ""        # 'arbetsorder' | 'offert' | 'kund'
    parent_label: str = ""
    parent_link: str = ""
    customer_name: Optional[str] = None


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

class ActiveTimer(BaseModel):
    """En tidtagning som fortfarande löper – vem som jobbar på vad just nu."""
    user_name: str
    order_id: int
    order_number: str
    started_at: datetime


class SalesAreaSummary(BaseModel):
    """En rad per försäljningsdel. `extra_*` skiljer sig åt: Feldbinder visar
    obetald provision, verkstadsdelen antalet som blivit arbetsorder."""
    kind: str
    label: str
    route: str
    currency: str
    open_leads: int = 0
    open_value: Decimal = Decimal("0")
    overdue_followups: int = 0
    sold_ytd_count: int = 0
    sold_ytd_value: Decimal = Decimal("0")
    extra_label: str = ""
    extra_value: str = ""


class UpcomingItem(BaseModel):
    """Post i listan över de närmaste 30 dagarna. Passerade datum tas med och
    märks som försenade istället för att tystna."""
    date: date
    kind: str            # 'leverans' | 'arbetsorder'
    label: str
    sub: Optional[str] = None
    link: str
    overdue: bool = False


class MonthlySalesPoint(BaseModel):
    """Sålt värde en månad. Valutorna hålls isär – EUR och SEK går inte att
    summera ihop, och grafen ritar en serie i taget."""
    month: str           # YYYY-MM
    feldbinder: Decimal = Decimal("0")
    verkstad: Decimal = Decimal("0")


class DashboardStats(BaseModel):
    # Kräver åtgärd
    overdue_followups: int = 0
    overdue_tasks: int = 0
    scheduled_today: int
    ready_to_invoice: int

    # Verkstaden
    total_open: int
    by_status: dict
    completed_this_week: int = 0
    active_timers: List[ActiveTimer] = []

    # Försäljning
    sales: List[SalesAreaSummary] = []
    monthly_sales: List[MonthlySalesPoint] = []

    # Listor
    upcoming: List[UpcomingItem] = []
    recent_orders: List[WorkOrderListItem]


# ── Pick lists ────────────────────────────────────────────────────────────────

class PickListLineCreate(BaseModel):
    article_id: Optional[int] = None
    article_number: Optional[str] = None
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
            # Radens sparade art.nr vinner – det finns kvar även efter att
            # artikelregistret rensats och lästs in på nytt
            article_number=line.article_number or (line.article.article_number if line.article else None),
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


class PickListScanResult(BaseModel):
    article_name: str
    line: PickListLineOut
    unknown: bool = False

# ── Försäljning / CRM ─────────────────────────────────────────────────────────

class SalesContactBlock(BaseModel):
    """Kunduppgifterna som visas likadant på förfrågan och på såld order."""
    customer_id: int
    customer_name: str = ""
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    customer_org_number: Optional[str] = None
    customer_city: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None


class SalesActivityCreate(BaseModel):
    name: str
    color: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    sort_order: Optional[int] = None


class SalesActivityUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    sort_order: Optional[int] = None


class SalesActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    color: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    sort_order: Optional[int]


class SalesScheduleItem(BaseModel):
    """En rad i Gantt-schemat. `source` skiljer automatiska poster (som kommer ur
    datumfälten) från egna aktiviteter, som är de enda som går att redigera."""
    name: str
    color: str = "#E2001A"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    source: str = "auto"          # 'auto' | 'custom'
    activity_id: Optional[int] = None


class SalesLeadNoteCreate(BaseModel):
    body: str
    kind: SalesNoteKind = SalesNoteKind.anteckning
    note_date: Optional[date] = None


class SalesLeadNoteUpdate(BaseModel):
    """Alla fält valfria – en rättning rör oftast bara texten."""
    body: Optional[str] = None
    kind: Optional[SalesNoteKind] = None
    note_date: Optional[date] = None


class SalesLeadNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    note_date: date
    kind: SalesNoteKind
    body: str
    created_at: datetime
    created_by_name: Optional[str] = None
    # Ordervyn visar även förfrågans logg – då är den historik och inte redigerbar
    from_lead: bool = False
    # Kundvyn samlar hela historiken; källan anges för de som kommer från en affär
    source_label: Optional[str] = None
    source_link: Optional[str] = None
    files: List["SalesLeadFileOut"] = []


class SalesLeadFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    group_label: Optional[str] = None
    original_name: str
    mime_type: Optional[str]
    size_bytes: Optional[int]
    uploaded_at: datetime


class SalesLeadCreate(BaseModel):
    customer_id: int
    kind: SalesLeadKind = SalesLeadKind.feldbinder
    description: Optional[str] = None
    activity_number: Optional[str] = None
    contact_person_id: Optional[int] = None
    product_type: Optional[str] = None
    size: Optional[str] = None
    quantity: int = 1
    status: SalesLeadStatus = SalesLeadStatus.ny
    date_request: Optional[date] = None
    date_sent_ffb: Optional[date] = None
    date_back_ffb: Optional[date] = None
    date_sent_customer: Optional[date] = None
    quote_number: Optional[str] = None
    estimated_value: Optional[Decimal] = None
    currency: str = "EUR"
    next_followup_date: Optional[date] = None
    assigned_to: Optional[int] = None
    external_link: Optional[str] = None
    lost_reason: Optional[str] = None
    notes: Optional[str] = None


class SalesLeadUpdate(SalesLeadCreate):
    # Alla fält valfria vid uppdatering – samma grepp som CustomerUpdate
    customer_id: Optional[int] = None
    # kind sätts vid skapandet och byts inte i efterhand – en verkstadsoffert och
    # en feldbinder-affär har olika fält och olika väg vidare när de säljs
    kind: Optional[SalesLeadKind] = None
    quantity: Optional[int] = None
    status: Optional[SalesLeadStatus] = None
    currency: Optional[str] = None


class SalesLeadListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: SalesLeadKind
    description: Optional[str] = None
    activity_number: Optional[str]
    customer_id: int
    customer_name: str = ""
    product_type: Optional[str]
    size: Optional[str]
    quantity: Optional[int]
    status: SalesLeadStatus
    date_request: Optional[date]
    date_sent_ffb: Optional[date]
    date_back_ffb: Optional[date]
    date_sent_customer: Optional[date]
    quote_number: Optional[str]
    estimated_value: Optional[Decimal]
    currency: Optional[str]
    next_followup_date: Optional[date]
    assignee_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    customer_org_number: Optional[str] = None
    contact_name: Optional[str] = None
    last_note: Optional[str] = None
    last_note_date: Optional[date] = None
    note_count: int = 0
    file_count: int = 0
    order_id: Optional[int] = None
    order_number: Optional[str] = None
    work_order_id: Optional[int] = None
    work_order_number: Optional[str] = None
    archived_at: Optional[datetime] = None


class SalesLeadOut(SalesLeadListItem):
    contact_person_id: Optional[int] = None
    # Listan visar bara namnet, men redigeringsformuläret behöver id:t för att
    # kunna förvälja ansvarig – utan det nollades fältet vid varje sparning
    assigned_to: Optional[int] = None
    external_link: Optional[str] = None
    lost_reason: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    lead_notes: List[SalesLeadNoteOut] = []
    files: List[SalesLeadFileOut] = []
    activities: List[SalesActivityOut] = []
    tasks: List["TaskOut"] = []


class SalesLeadConvert(BaseModel):
    """Fälten som fylls i när en förfrågan blir en order."""
    order_number: Optional[str] = None
    sold_date: Optional[date] = None
    price: Optional[Decimal] = None
    commission: Optional[Decimal] = None


class SalesMilestoneDefCreate(BaseModel):
    key: str
    group_label: str
    label: str
    value_type: MilestoneValueType = MilestoneValueType.datum
    sort_order: int = 0


class SalesMilestoneDefUpdate(BaseModel):
    group_label: Optional[str] = None
    label: Optional[str] = None
    value_type: Optional[MilestoneValueType] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class SalesMilestoneDefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    key: str
    group_label: str
    label: str
    value_type: MilestoneValueType
    sort_order: int
    is_active: bool


class SalesOrderMilestoneUpdate(BaseModel):
    value_date: Optional[date] = None
    value_text: Optional[str] = None
    completed: Optional[bool] = None


class SalesOrderMilestoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    def_id: int
    key: str
    group_label: str
    label: str
    value_type: MilestoneValueType
    sort_order: int
    value_date: Optional[date] = None
    value_text: Optional[str] = None
    completed: bool = False
    updated_at: Optional[datetime] = None


class SalesOrderCreate(BaseModel):
    customer_id: int
    lead_id: Optional[int] = None
    order_number: Optional[str] = None
    serial_number: Optional[str] = None
    product_type: Optional[str] = None
    price: Optional[Decimal] = None
    currency: str = "EUR"
    commission: Optional[Decimal] = None
    commission_paid_date: Optional[date] = None
    sold_date: Optional[date] = None
    delivery_date: Optional[date] = None
    planned_delivery: Optional[date] = None
    delivery_week: Optional[str] = None
    registration_number: Optional[str] = None
    weight_kg: Optional[int] = None
    visit_ffb: Optional[bool] = None
    sort_index: Optional[int] = None
    notes: Optional[str] = None


class SalesOrderUpdate(SalesOrderCreate):
    customer_id: Optional[int] = None
    currency: Optional[str] = None


class SalesOrderFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    group_label: Optional[str] = None
    aoc_id: Optional[int] = None
    original_name: str
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    uploaded_at: datetime


class SalesOrderAocCreate(BaseModel):
    aoc_number: Optional[str] = None
    sent_customer: Optional[date] = None
    mailed_ffb: Optional[date] = None
    cost_eur: Optional[Decimal] = None
    notes: Optional[str] = None
    sort_order: Optional[int] = None


class SalesOrderAocUpdate(SalesOrderAocCreate):
    pass


class SalesOrderAocOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    aoc_number: Optional[str]
    sent_customer: Optional[date]
    mailed_ffb: Optional[date]
    cost_eur: Optional[Decimal]
    notes: Optional[str]
    sort_order: Optional[int]
    files: List[SalesOrderFileOut] = []


class SalesOrderListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lead_id: Optional[int]
    customer_id: int
    customer_name: str = ""
    order_number: Optional[str]
    serial_number: Optional[str]
    product_type: Optional[str]
    price: Optional[Decimal]
    currency: Optional[str]
    commission: Optional[Decimal]
    commission_paid_date: Optional[date]
    sold_date: Optional[date]
    delivery_date: Optional[date]
    planned_delivery: Optional[date]
    delivery_week: Optional[str]
    registration_number: Optional[str]
    weight_kg: Optional[int]
    visit_ffb: Optional[bool]
    sort_index: Optional[int]
    archived_at: Optional[datetime] = None
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    customer_org_number: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    milestones_done: int = 0
    milestones_total: int = 0


class SalesOrderOut(SalesOrderListItem):
    notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    milestones: List[SalesOrderMilestoneOut] = []
    aocs: List[SalesOrderAocOut] = []
    files: List[SalesOrderFileOut] = []
    order_notes: List[SalesLeadNoteOut] = []
    activities: List[SalesActivityOut] = []


class SalesCommissionRow(BaseModel):
    order_id: int
    order_number: Optional[str]
    customer_name: str
    product_type: Optional[str]
    sold_date: Optional[date]
    price: Optional[Decimal]
    commission: Optional[Decimal]
    commission_paid_date: Optional[date]


class SalesCommissionSummary(BaseModel):
    year: Optional[int]
    rows: List[SalesCommissionRow]
    total_price: Decimal = Decimal("0")
    total_commission: Decimal = Decimal("0")
    paid_commission: Decimal = Decimal("0")
    unpaid_commission: Decimal = Decimal("0")


class SalesPipelineStats(BaseModel):
    by_status: dict
    open_leads: int = 0
    overdue_followups: int = 0
    open_value: Decimal = Decimal("0")
    currency: str = "EUR"


class SalesLeadToWorkOrder(BaseModel):
    """Fälten som fylls i när en verkstadsoffert blir en arbetsorder."""
    order_number: Optional[str] = None
    description: Optional[str] = None
    vehicle_id: Optional[int] = None
    assigned_to: Optional[int] = None
    scheduled_date: Optional[datetime] = None


# ── FFB-beställning ───────────────────────────────────────────────────────────

class FfbOrderUpdate(BaseModel):
    """Beställningens egna fält – de speglar Word-mallens rutor.

    Kundblocket saknas med flit: namn, adress, VAT, land, telefon, mail och
    kontaktperson hämtas ur kunden och ändras därför på kundkortet.
    """
    doc_date: Optional[date] = None

    quantity: Optional[str] = None
    quotation_number: Optional[str] = None
    delivery_time: Optional[str] = None
    product_type: Optional[str] = None
    part_no: Optional[str] = None
    part_delivery_time: Optional[str] = None
    volume_approx: Optional[str] = None
    transport_of: Optional[str] = None
    country_of_registration: Optional[str] = None
    drawing_number: Optional[str] = None
    special_feature: Optional[str] = None

    chassis_make: Optional[str] = None
    wheel_base: Optional[str] = None
    fo_number: Optional[str] = None
    chassis_delivery_time: Optional[str] = None

    terms_payment: Optional[str] = None
    terms_delivery: Optional[str] = None

    order_text: Optional[str] = None


class FfbOrderOut(FfbOrderUpdate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    # Tomt så länge ingen har sparat beställningen – vyn visar den som ogranskad
    updated_by: Optional[int] = None
    updated_at: Optional[datetime] = None

    # Hämtas ur kunden och förfrågan vid varje läsning. Går inte att skriva till
    # via API:et – de ändras på kundkortet respektive förfrågan.
    vat_number: Optional[str] = None
    customer_number: Optional[str] = None
    customer_name: Optional[str] = None
    address: Optional[str] = None
    postal_city: Optional[str] = None
    country: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    contact_person: Optional[str] = None


# ── FFB-offertförfrågan ───────────────────────────────────────────────────────

class FfbQuoteUpdate(BaseModel):
    """Offertförfrågans egna fält. Kundblocket saknas med flit – det hämtas ur
    kunden, precis som på beställningen."""
    doc_date: Optional[date] = None

    product_type: Optional[str] = None
    volume_approx: Optional[str] = None
    transport_of: Optional[str] = None
    country_of_registration: Optional[str] = None
    drawing_number: Optional[str] = None
    special_feature: Optional[str] = None

    chassis_make: Optional[str] = None
    wheel_base: Optional[str] = None
    fo_number: Optional[str] = None

    terms_payment: Optional[str] = None
    terms_delivery: Optional[str] = None

    request_text: Optional[str] = None


class FfbQuoteOut(FfbQuoteUpdate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lead_id: int
    updated_by: Optional[int] = None
    updated_at: Optional[datetime] = None

    # Hämtas ur kunden och förfrågan vid varje läsning
    vat_number: Optional[str] = None
    customer_number: Optional[str] = None
    customer_name: Optional[str] = None
    address: Optional[str] = None
    postal_city: Optional[str] = None
    country: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    contact_person: Optional[str] = None


Token.model_rebuild()
