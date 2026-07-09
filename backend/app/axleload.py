"""Axeltrycks-/lastfördelningsberäkning för tankplacering på ett 2-punkts-chassi
(framaxel + bakaxel/boggi-centrum).

Klassisk momentbalans över hjulbasen ``L`` (framaxel → bakaxelgruppens centrum).
Tanken (payload) får sin vikt ur skillnaden mellan lastad totalvikt och tomvikt,
och placeras så att önskat bakaxeltryck uppnås:

    tankvikt   = lastad_total − tom_total
    a (TP)     = L · (önskat_bak − tom_bak) / tankvikt      (bakom framaxeln)
    fram_last  = tom_fram + tankvikt · (L − a) / L
    bak_last   = tom_bak  + tankvikt · a / L

Tyngdpunkten antas i tankens geometriska mitt: ``a = tank_front + längd/2``.
Längder i mm, vikter i kg.
"""
from dataclasses import dataclass, asdict
from typing import List, Optional


@dataclass
class AxleLoadResult:
    wheelbase: float
    tank_length: float
    tank_weight: float
    cg: float
    tank_front: float
    empty_front: float
    empty_rear: float
    empty_total: float
    load_front: float
    load_rear: float
    loaded_total: float
    desired_front: float
    desired_rear: float
    max_front: float
    max_rear: float
    max_total: float
    front_util: float
    rear_util: float
    total_util: float
    warnings: List[str]

    def to_dict(self):
        return asdict(self)


def _pct(part, whole):
    return round(100 * part / whole, 1) if whole else 0.0


# ── Sidvys-geometri (lastbilssiluett) ─────────────────────────────────────────
# Visuella konstanter (mm) delade av PDF och webbritning. Framaxel = x 0,
# bakåt = +x, marken = y 0, y uppåt.
WHEEL_R = 520.0
BEAM_BOT = 640.0
BEAM_TOP = 820.0
TANK_GAP = 40.0
TANK_H = 2000.0
CAB_LEN = 2350.0
CAB_H = 2500.0
CAB_BEVEL = 420.0


def _arc_pts(cx, cy, r, a0, a1, n=18):
    import math
    return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
            for a in [a0 + (a1 - a0) * i / n for i in range(n + 1)]]


def dimensions(front_overhang: float, axle_offsets: List[float], wheelbase: float,
               tank_front: float, tank_length: float, cg: float) -> List[dict]:
    """Måttkedja i sidvyn (världskoordinater, mm). Varje mått: horisontell linje
    mellan a→b på höjden y, med etikett. Delas av PDF och webbritning.

    Tyngdpunkten (TP) måtts från **andra axeln** (drivaxeln), enligt kundens ritning.
    """
    offs = sorted(axle_offsets)
    fo = front_overhang or 0.0
    L = wheelbase
    tank_top = BEAM_TOP + TANK_GAP + TANK_H
    cab_top = BEAM_TOP + CAB_H
    ax2 = offs[1] if len(offs) >= 2 else L
    dims: List[dict] = []
    # ── nedre måttkedja ──
    if fo > 0:
        dims.append({"a": -fo, "b": 0.0, "y": -430.0, "label": f"{fo:.0f}"})
    dims.append({"a": 0.0, "b": ax2, "y": -430.0, "label": f"{ax2 - offs[0]:.0f}"})
    if len(offs) >= 3:
        dims.append({"a": offs[1], "b": offs[2], "y": -430.0, "label": f"{offs[2] - offs[1]:.0f}"})
    dims.append({"a": 0.0, "b": L, "y": -680.0, "label": f"Techn. {L:.0f}"})
    # ── övre måttkedja (högst upp) ──
    dims.append({"a": 0.0, "b": tank_front, "y": tank_top + 980, "label": f"{tank_front:.0f}"})
    dims.append({"a": tank_front, "b": tank_front + tank_length, "y": tank_top + 980, "label": f"{tank_length:.0f}"})
    # ── TP från andra axeln (strax ovan tanken) ──
    dims.append({"a": ax2, "b": cg, "y": tank_top + 230, "label": f"{cg - ax2:.0f}", "accent": True})
    return dims


def silhouette(front_overhang: float, axle_offsets: List[float],
               tank_front: float, tank_length: float) -> dict:
    """Bygger en lastbilssiluett i sidvy (hytt, vindruta, stötfångare, tank-baffler,
    stänkskärmar) i världskoordinater (mm, y uppåt). Delas av PDF och webbritning."""
    fo = front_overhang or 1400.0
    cab_front = -fo
    cab_back = cab_front + CAB_LEN
    cab_top = BEAM_TOP + CAB_H
    tank_bot = BEAM_TOP + TANK_GAP
    tank_top = tank_bot + TANK_H

    cab = [
        (cab_front, BEAM_TOP),
        (cab_front, cab_top - CAB_BEVEL),
        (cab_front + CAB_BEVEL, cab_top),
        (cab_back, cab_top),
        (cab_back, BEAM_TOP),
    ]
    windshield = [
        (cab_front + 210, cab_top - 210),
        (cab_front + 1180, cab_top - 210),
        (cab_front + 1180, cab_top - 830),
        (cab_front + 470, cab_top - 830),
    ]
    bumper = [
        (cab_front - 150, 300.0),
        (cab_front + 160, 300.0),
        (cab_front + 160, 720.0),
        (cab_front - 150, 720.0),
    ]
    baffles = [
        [(tank_front + tank_length * f, tank_bot + 130), (tank_front + tank_length * f, tank_top - 130)]
        for f in (0.30, 0.5, 0.70)
    ]
    fenders = [_arc_pts(cx, WHEEL_R, WHEEL_R * 1.22, 8, 172) for cx in axle_offsets]

    return {
        "cab": cab,
        "windshield": windshield,
        "bumper": bumper,
        "baffles": baffles,
        "fenders": fenders,
        "beam_top": BEAM_TOP,
        "beam_bot": BEAM_BOT,
        "tank_bot": tank_bot,
        "tank_top": tank_top,
        "wheel_r": WHEEL_R,
    }


def compute(
    wheelbase: float,
    empty_front: float,
    empty_rear: float,
    empty_total: float,
    tank_length: float,
    loaded_total: float,
    desired_front: float,
    desired_rear: float,
    max_front: float,
    max_rear: float,
) -> AxleLoadResult:
    L = wheelbase
    if L <= 0:
        raise ValueError("Hjulbas måste vara större än noll")
    if tank_length < 0:
        raise ValueError("Tanklängd kan inte vara negativ")

    tank_weight = loaded_total - empty_total
    if tank_weight <= 0:
        raise ValueError("Lastad totalvikt måste vara större än total tomvikt")

    # Placeras efter önskat bakaxeltryck (den bindande axeln för tankbilar)
    cg = (desired_rear - empty_rear) * L / tank_weight
    tank_front = cg - tank_length / 2

    load_front = empty_front + tank_weight * (L - cg) / L
    load_rear = empty_rear + tank_weight * cg / L
    max_total = max_front + max_rear

    warnings: List[str] = []
    if abs((empty_front + empty_rear) - empty_total) > 1:
        warnings.append("Tomvikt fram + bak stämmer inte med total tomvikt")
    if abs((desired_front + desired_rear) - loaded_total) > 1:
        warnings.append("Önskat axeltryck fram + bak stämmer inte med lastad totalvikt – placering sätts efter bakaxeln")
    if max_front and load_front > max_front:
        warnings.append(f"Framaxeln överskrider max ({load_front:.0f} > {max_front:.0f} kg)")
    if max_rear and load_rear > max_rear:
        warnings.append(f"Bakaxeln överskrider max ({load_rear:.0f} > {max_rear:.0f} kg)")
    if load_front < 0:
        warnings.append("Framaxeln avlastas helt (negativ last)")
    if cg < 0 or cg > L:
        warnings.append("Tankens tyngdpunkt hamnar utanför hjulbasen")

    return AxleLoadResult(
        wheelbase=round(L, 1),
        tank_length=round(tank_length, 1),
        tank_weight=round(tank_weight, 1),
        cg=round(cg, 1),
        tank_front=round(tank_front, 1),
        empty_front=round(empty_front, 1),
        empty_rear=round(empty_rear, 1),
        empty_total=round(empty_total, 1),
        load_front=round(load_front, 1),
        load_rear=round(load_rear, 1),
        loaded_total=round(loaded_total, 1),
        desired_front=round(desired_front, 1),
        desired_rear=round(desired_rear, 1),
        max_front=round(max_front, 1),
        max_rear=round(max_rear, 1),
        max_total=round(max_total, 1),
        front_util=_pct(load_front, max_front),
        rear_util=_pct(load_rear, max_rear),
        total_util=_pct(loaded_total, max_total),
        warnings=warnings,
    )
