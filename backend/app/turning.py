"""Svängradieberäkning (swept path / offtracking) för stel lastbil med
godtyckligt antal axlar och en eller flera styrbara axlar.

Modellen är steady-state (konstant radie) enligt lågfartsgeometrin som t.ex.
CornerWin använder:

* De **fasta** (icke-styrbara) axlarna kan inte alla vara tangenta till samma
  cirkel – vändcentrum läggs på linjen genom deras geometriska mittpunkt
  (bogie-centrum), ``u_c``.
* **Effektiv hjulbas** ``L_eff = u_c − u_styr`` där ``u_styr`` är främre
  styrande axeln. ``R = L_eff / tan(δ)`` (radie till centrumlinjen vid ``u_c``).
* Varje styrbar axel får sin ideala vinkel ``δᵢ = atan((u_c − uᵢ) / R)``.
* ``R_in = R − W/2``  och  ``R_ut = max(hörnavstånd från vändcentrum)``.

Alla längder i mm, vinklar i grader. Punkter returneras i ett system där
vändcentrum ligger i origo och y pekar uppåt (matematisk).
"""
import math
from dataclasses import dataclass, asdict, field
from typing import List, Tuple, Optional

Point = Tuple[float, float]


@dataclass
class Axle:
    offset: float          # mm bakom främre axeln (främre axeln = 0)
    steered: bool = False


@dataclass
class TruckDims:
    axles: List[Axle]
    width: float
    front_overhang: float = 0.0    # främre axel → front
    rear_overhang: float = 0.0     # bakre axel → bak


@dataclass
class TurningResult:
    steering_angle: float
    r_rear: float          # radie till referenspunkten (fasta axlarnas centrum)
    r_front: float
    r_out: float
    r_in: float
    swept_width: float
    center: Point
    arc_in: List[Point]
    arc_out: List[Point]
    body: List[Point]
    cab: List[Point]
    ghost: List[Point]
    wheels: List[List[Point]]
    axle_angles: List[dict]

    def to_dict(self):
        return asdict(self)


def _arc(r: float, a0: float, a1: float, n: int = 72) -> List[Point]:
    return [
        (r * math.cos(a0 + (a1 - a0) * i / n), r * math.sin(a0 + (a1 - a0) * i / n))
        for i in range(n + 1)
    ]


@dataclass
class _Geom:
    """Kärngeometrin vid en given styrvinkel – radier utan ritpolygoner."""
    axles: List[Axle]
    width: float
    u_c: float          # fasta axlarnas centrum (vändcentrums referenslinje)
    u_s: float          # främre styrande axeln
    l_eff: float        # effektiv hjulbas
    r_center: float     # R – radie till centrumlinjen vid u_c
    r_out: float
    r_in: float
    r_front: float
    u_front: float
    u_end: float


def _geometry(dims: TruckDims, steering_angle_deg: float) -> _Geom:
    """Radierna för en styrvinkel. Delas av compute() och av EU-manöverprovet,
    som söker den styrvinkel där ytterradien möter 12,50 m-cirkeln."""
    axles = sorted(dims.axles, key=lambda a: a.offset)
    W = dims.width
    fo, ro = dims.front_overhang, dims.rear_overhang
    if len(axles) < 2:
        raise ValueError("Minst två axlar krävs")
    if W <= 0:
        raise ValueError("Bredd måste vara större än noll")
    if not (0 < steering_angle_deg < 90):
        raise ValueError("Styrvinkeln måste vara mellan 0 och 90 grader")

    steered = [a for a in axles if a.steered]
    ref_group = [a for a in axles if not a.steered] or axles  # fasta axlar (annars alla)
    u_c = sum(a.offset for a in ref_group) / len(ref_group)
    primary = min(steered, key=lambda a: a.offset) if steered else axles[0]
    u_s = primary.offset
    l_eff = u_c - u_s
    if l_eff <= 0:
        raise ValueError("Den styrande axeln måste ligga framför de fasta axlarna")

    R = l_eff / math.tan(math.radians(steering_angle_deg))
    u_front, u_end = -fo, axles[-1].offset + ro
    corners = [(u_front, W / 2), (u_front, -W / 2), (u_end, -W / 2), (u_end, W / 2)]
    return _Geom(
        axles=axles, width=W, u_c=u_c, u_s=u_s, l_eff=l_eff, r_center=R,
        r_out=max(math.hypot(u - u_c, R - y) for u, y in corners),
        r_in=R - W / 2,
        r_front=math.hypot(u_s - u_c, R),        # = l_eff / sin(δ)
        u_front=u_front, u_end=u_end,
    )


def compute(
    dims: TruckDims,
    steering_angle_deg: float,
    sweep_deg: float = 45.0,
    ghost_deg: float = 8.0,
    arc_span_deg: Tuple[float, float] = (4.0, 90.0),
) -> TurningResult:
    g = _geometry(dims, steering_angle_deg)
    axles, W = g.axles, g.width
    u_c, R = g.u_c, g.r_center
    u_front, u_end = g.u_front, g.u_end
    r_out, r_in, r_front = g.r_out, g.r_in, g.r_front
    swept = r_out - r_in

    # --- Transform: kroppspunkt (u bakåt+, y sidled+) → världskoord vid svängvinkel phi ---
    def T(u, y, phi):
        c, s = math.cos(phi), math.sin(phi)
        return ((R - y) * c - (u_c - u) * s, (R - y) * s + (u_c - u) * c)

    phi = math.radians(sweep_deg)
    gphi = math.radians(ghost_deg)

    def rect(u0, u1, y0, y1, p):
        return [T(u0, y0, p), T(u1, y0, p), T(u1, y1, p), T(u0, y1, p)]

    body = rect(u_front, u_end, -W / 2, W / 2, phi)
    ghost = rect(u_front, u_end, -W / 2, W / 2, gphi)
    cab_len = min(2200.0, (u_end - u_front) * 0.4)
    cab = rect(u_front, u_front + cab_len, -W / 2 * 0.96, W / 2 * 0.96, phi)

    # --- Hjul (roterade för styrbara axlar) ---
    wl, ww = 900.0, 360.0
    yw = W / 2 * 0.82
    wheels: List[List[Point]] = []
    axle_angles: List[dict] = []
    for a in axles:
        ang = math.atan2(u_c - a.offset, R) if a.steered else 0.0
        axle_angles.append({"offset": a.offset, "steered": a.steered, "angle": round(math.degrees(ang), 1)})
        ca, sa = math.cos(-ang), math.sin(-ang)   # rotera hjulet i kroppsplanet
        for side in (yw, -yw):
            local = [(-wl / 2, -ww / 2), (wl / 2, -ww / 2), (wl / 2, ww / 2), (-wl / 2, ww / 2)]
            poly = []
            for du, dy in local:
                ru = du * ca - dy * sa
                ry = du * sa + dy * ca
                poly.append(T(a.offset + ru, side + ry, phi))
            wheels.append(poly)

    a0, a1 = math.radians(arc_span_deg[0]), math.radians(arc_span_deg[1])
    return TurningResult(
        steering_angle=steering_angle_deg,
        r_rear=round(R, 1),
        r_front=round(r_front, 1),
        r_out=round(r_out, 1),
        r_in=round(r_in, 1),
        swept_width=round(swept, 1),
        center=(0.0, 0.0),
        arc_in=_arc(r_in, a0, a1),
        arc_out=_arc(r_out, a0, a1),
        body=body,
        cab=cab,
        ghost=ghost,
        wheels=wheels,
        axle_angles=axle_angles,
    )


# ── Manöverprov enligt (EU) 2021/535 bilaga XIII avsnitt D ────────────────────
#
# Fordonet ska kunna manövreras inom en cirkelring som begränsas av två
# koncentriska cirklar: ytterradie 12,50 m och innerradie 5,30 m. Provet körs
# med fordonets yttersta punkt längs ytterkretsen – ingen del får då nå innanför
# innercirkeln. Skillnaden R_ut − R_in är fordonets utsvängning (svepbredd) och
# får alltså inte överstiga 7,20 m.

EU_OUTER_RADIUS = 12500.0
EU_INNER_RADIUS = 5300.0
EU_MAX_SWEPT = EU_OUTER_RADIUS - EU_INNER_RADIUS      # 7 200 mm
EU_STANDARD = "(EU) 2021/535 bilaga XIII avsnitt D"

# Antas när fordonet saknar registrerad max styrvinkel. Utfallet beror helt på
# detta värde, så ritningen måste flagga att det är ett antagande.
DEFAULT_MAX_STEERING = 45.0


@dataclass
class Compliance:
    standard: str
    outer_limit: float
    inner_limit: float
    max_swept: float
    max_steering_angle: float
    angle: Optional[float]        # styrvinkel där R_ut = 12,50 m
    reachable: bool               # klarar fordonet att hålla sig innanför ytterkretsen
    r_out: float
    r_in: float
    swept_width: float
    outer_ok: bool
    inner_ok: bool
    passed: bool
    r_out_at_max: float           # minsta uppnåeliga ytterradie (fullt styrutslag)
    r_in_at_max: float
    swept_at_max: float
    l_eff: float                  # effektiv hjulbas i provet
    r_center: float               # radie till centrumlinjen vid fasta axlarnas centrum

    def to_dict(self):
        return asdict(self)


def angle_for_r_out(dims: TruckDims, target_r_out: float,
                    max_angle: float = 45.0) -> Optional[float]:
    """Styrvinkeln där ytterradien blir ``target_r_out``.

    R_ut avtar monotont med styrvinkeln, så intervallet halveras. Returnerar
    None om radien inte kan nås inom ``max_angle`` (fordonet svänger för brett)."""
    lo, hi = 0.05, max_angle
    if _geometry(dims, hi).r_out > target_r_out:
        return None
    for _ in range(48):
        mid = (lo + hi) / 2
        if _geometry(dims, mid).r_out > target_r_out:
            lo = mid
        else:
            hi = mid
    return round(hi, 2)


def check_eu(dims: TruckDims, max_steering_angle: float = 45.0) -> Compliance:
    """Kör manöverprovet och returnerar utfallet med alla mellanvärden."""
    g_max = _geometry(dims, max_steering_angle)
    angle = angle_for_r_out(dims, EU_OUTER_RADIUS, max_angle=max_steering_angle)
    reachable = angle is not None
    g = _geometry(dims, angle) if reachable else g_max
    inner_ok = reachable and g.r_in >= EU_INNER_RADIUS
    return Compliance(
        standard=EU_STANDARD,
        outer_limit=EU_OUTER_RADIUS,
        inner_limit=EU_INNER_RADIUS,
        max_swept=EU_MAX_SWEPT,
        max_steering_angle=max_steering_angle,
        angle=angle,
        reachable=reachable,
        r_out=round(g.r_out, 1),
        r_in=round(g.r_in, 1),
        swept_width=round(g.r_out - g.r_in, 1),
        outer_ok=reachable,
        inner_ok=inner_ok,
        passed=bool(reachable and inner_ok),
        r_out_at_max=round(g_max.r_out, 1),
        r_in_at_max=round(g_max.r_in, 1),
        swept_at_max=round(g_max.r_out - g_max.r_in, 1),
        l_eff=round(g.l_eff, 1),
        r_center=round(g.r_center, 1),
    )


def reference_arc(radius: float, arc_span_deg: Tuple[float, float] = (4.0, 90.0),
                  n: int = 96) -> List[Point]:
    """Referenscirkelbåge (12,50 m / 5,30 m) i svepets koordinatsystem."""
    return _arc(radius, math.radians(arc_span_deg[0]), math.radians(arc_span_deg[1]), n)


def dims_from_vehicle(v) -> Optional[TruckDims]:
    """Bygger TruckDims från ett Vehicle-objekt.

    Använder i första hand ``v.axles`` (JSON-lista med ``{offset_mm, steered}``).
    Faller tillbaka på ``wheelbase_mm`` (2-axlad, främre styrd) för äldre fordon.
    Returnerar None om varken axelkonfiguration eller hjulbas + bredd finns.
    """
    W = v.width_mm
    if not W:
        return None

    raw = getattr(v, "axles", None)
    axles: List[Axle] = []
    if raw:
        for i, a in enumerate(raw):
            off = a.get("offset_mm", a.get("offset"))
            if off is None:
                continue
            steered = a.get("steered", i == 0)
            axles.append(Axle(offset=float(off), steered=bool(steered)))
    if len(axles) < 2 and v.wheelbase_mm:
        axles = [Axle(0.0, True), Axle(float(v.wheelbase_mm), False)]
    if len(axles) < 2:
        return None
    # Säkerställ att minst en axel är styrbar (främre)
    if not any(a.steered for a in axles):
        axles[0].steered = True

    return TruckDims(
        axles=axles,
        width=float(W),
        front_overhang=float(v.front_overhang_mm or 0),
        rear_overhang=float(v.rear_overhang_mm or 0),
    )
