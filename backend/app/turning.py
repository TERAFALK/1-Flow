"""Svängradieberäkning (swept path / offtracking) för stel lastbil.

Ren geometri – inga ramverksberoenden, enkel att enhetstesta. Modellen är
steady-state (konstant radie): fordonet kör runt en cirkel och vi räknar ut
ytter- och innerradie samt sveper ut karossens konturpunkter.

Formler (Ackermann-geometri, en stel enhet):
    R_bakaxel = L / tan(δ)
    R_in      = R_bakaxel − W/2                       (inre svepradie)
    R_ut      = √((R_bakaxel + W/2)² + (L + a_f)²)     (yttre främre hörn)
    R_fram    = L / sin(δ)                             (framaxelns radie)

Alla längder i mm, vinklar i grader. Koordinatpunkterna returneras i ett
system där vändcentrum ligger i origo och y pekar uppåt (matematisk).
"""
import math
from dataclasses import dataclass, asdict
from typing import List, Tuple, Optional

Point = Tuple[float, float]


@dataclass
class TruckDims:
    wheelbase: float          # L  – hjulbas (framaxel → bakaxel)
    width: float              # W  – total bredd
    front_overhang: float = 0.0   # a_f – framaxel → front
    rear_overhang: float = 0.0    # a_r – bakaxel → bak


@dataclass
class TurningResult:
    steering_angle: float
    r_rear: float
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
    axle_front: List[Point]
    axle_rear: List[Point]

    def to_dict(self):
        return asdict(self)


def _point(r_rear: float, phi: float, l: float, w: float) -> Point:
    """Punkt med längdoffset ``l`` (framåt +) och sidooffset ``w`` (utåt +)
    relativt bakaxelns mitt, när fordonet befinner sig vid svängvinkeln ``phi``."""
    ur = (math.cos(phi), math.sin(phi))     # radiellt utåt
    ut = (-math.sin(phi), math.cos(phi))    # framåt (tangent)
    x = (r_rear + w) * ur[0] + l * ut[0]
    y = (r_rear + w) * ur[1] + l * ut[1]
    return (x, y)


def _arc(r: float, a0: float, a1: float, n: int = 64) -> List[Point]:
    return [
        (r * math.cos(a0 + (a1 - a0) * i / n), r * math.sin(a0 + (a1 - a0) * i / n))
        for i in range(n + 1)
    ]


def compute(
    dims: TruckDims,
    steering_angle_deg: float,
    sweep_deg: float = 50.0,
    ghost_deg: float = 9.0,
    arc_span_deg: Tuple[float, float] = (4.0, 90.0),
) -> TurningResult:
    if dims.wheelbase <= 0 or dims.width <= 0:
        raise ValueError("Hjulbas och bredd måste vara större än noll")
    if not (0 < steering_angle_deg < 90):
        raise ValueError("Styrvinkeln måste vara mellan 0 och 90 grader")

    d = math.radians(steering_angle_deg)
    L, W = dims.wheelbase, dims.width
    af, ar = dims.front_overhang, dims.rear_overhang

    r_rear = L / math.tan(d)
    r_front = L / math.sin(d)
    r_in = r_rear - W / 2
    r_out = math.hypot(r_rear + W / 2, L + af)
    swept = r_out - r_in

    a0, a1 = math.radians(arc_span_deg[0]), math.radians(arc_span_deg[1])
    phi = math.radians(sweep_deg)
    gphi = math.radians(ghost_deg)

    def body_at(p: float) -> List[Point]:
        return [
            _point(r_rear, p, L + af, W / 2),
            _point(r_rear, p, L + af, -W / 2),
            _point(r_rear, p, -ar, -W / 2),
            _point(r_rear, p, -ar, W / 2),
        ]

    cab = [
        _point(r_rear, phi, L + af, W / 2 * 0.92),
        _point(r_rear, phi, L + af, -W / 2 * 0.92),
        _point(r_rear, phi, L - 0.3, -W / 2 * 0.92),
        _point(r_rear, phi, L - 0.3, W / 2 * 0.92),
    ]

    return TurningResult(
        steering_angle=steering_angle_deg,
        r_rear=round(r_rear, 1),
        r_front=round(r_front, 1),
        r_out=round(r_out, 1),
        r_in=round(r_in, 1),
        swept_width=round(swept, 1),
        center=(0.0, 0.0),
        arc_in=_arc(r_in, a0, a1),
        arc_out=_arc(r_out, a0, a1),
        body=body_at(phi),
        cab=cab,
        ghost=body_at(gphi),
        axle_front=[_point(r_rear, phi, L, W / 2 * 0.86), _point(r_rear, phi, L, -W / 2 * 0.86)],
        axle_rear=[_point(r_rear, phi, 0, W / 2 * 0.86), _point(r_rear, phi, 0, -W / 2 * 0.86)],
    )


def dims_from_vehicle(v, defaults=None) -> Optional[TruckDims]:
    """Bygger TruckDims från ett Vehicle-objekt. Returnerar None om
    hjulbas eller bredd saknas (då går ingen beräkning att göra)."""
    L = v.wheelbase_mm
    W = v.width_mm
    if not L or not W:
        return None
    return TruckDims(
        wheelbase=float(L),
        width=float(W),
        front_overhang=float(v.front_overhang_mm or 0),
        rear_overhang=float(v.rear_overhang_mm or 0),
    )
