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
