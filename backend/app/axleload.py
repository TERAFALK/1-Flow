"""Axeltrycks-/lastfördelningsberäkning för tankplacering på ett 2-axlat chassi.

Klassisk momentbalans (hävstångsprincip) över hjulbasen ``L``. En tank som väger
``W`` med tyngdpunkt ``a`` mm bakom framaxeln ger:

    Bakaxel  += W · a / L
    Framaxel += W · (L − a) / L

Tyngdpunkten antas ligga i tankens geometriska mitt, dvs
``a = tank_front + tank_length / 2`` där ``tank_front`` är tankens främre kant
räknat bakom framaxeln (kan vara negativ = framför framaxeln).

Alla längder i mm, vikter i kg.
"""
from dataclasses import dataclass, asdict
from typing import List, Optional


@dataclass
class AxleLoadResult:
    wheelbase: float
    empty_front: float
    empty_rear: float
    tank_weight: float
    tank_length: float
    tank_front: float        # tankens främre kant bakom framaxeln
    cg: float                # tyngdpunkt bakom framaxeln
    front_load: float
    rear_load: float
    total: float
    front_pct: float
    rear_pct: float
    warnings: List[str]

    def to_dict(self):
        return asdict(self)


def compute(
    wheelbase: float,
    empty_front: float,
    empty_rear: float,
    tank_weight: float,
    tank_length: float,
    tank_front: Optional[float] = None,
    target_rear: Optional[float] = None,
) -> AxleLoadResult:
    L = wheelbase
    if L <= 0:
        raise ValueError("Hjulbas måste vara större än noll")
    if tank_weight < 0 or tank_length < 0:
        raise ValueError("Tankvikt och tanklängd kan inte vara negativa")

    # Inverst läge: lös tankens placering för att träffa önskat bakaxeltryck
    if target_rear is not None:
        if tank_weight <= 0:
            raise ValueError("Tankvikt krävs för att lösa placeringen")
        cg = (target_rear - empty_rear) * L / tank_weight
        tank_front = cg - tank_length / 2
    else:
        if tank_front is None:
            tank_front = 0.0
        cg = tank_front + tank_length / 2

    front_load = empty_front + tank_weight * (L - cg) / L
    rear_load = empty_rear + tank_weight * cg / L
    total = empty_front + empty_rear + tank_weight

    warnings: List[str] = []
    if front_load < 0:
        warnings.append("Framaxeln avlastas helt (negativ last) – tanken sitter för långt bak")
    if rear_load < 0:
        warnings.append("Bakaxeln avlastas helt (negativ last) – tanken sitter för långt fram")
    if cg < 0:
        warnings.append("Tyngdpunkten hamnar framför framaxeln")
    elif cg > L:
        warnings.append("Tyngdpunkten hamnar bakom bakaxeln")

    return AxleLoadResult(
        wheelbase=round(L, 1),
        empty_front=round(empty_front, 1),
        empty_rear=round(empty_rear, 1),
        tank_weight=round(tank_weight, 1),
        tank_length=round(tank_length, 1),
        tank_front=round(tank_front, 1),
        cg=round(cg, 1),
        front_load=round(front_load, 1),
        rear_load=round(rear_load, 1),
        total=round(total, 1),
        front_pct=round(100 * front_load / total, 1) if total else 0.0,
        rear_pct=round(100 * rear_load / total, 1) if total else 0.0,
        warnings=warnings,
    )
