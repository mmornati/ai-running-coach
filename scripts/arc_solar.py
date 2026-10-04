#!/usr/bin/env python3
"""Position du soleil, lever/coucher et crépuscule civil — pur, stdlib, sans réseau
(#184, épopée #170 : pénalité de nuit dans le pacing de course).

## Méthode

Algorithme du calculateur solaire de la NOAA (équations « General Solar Position
Calculations » : longitude moyenne, anomalie moyenne, équation du centre,
obliquité corrigée, déclinaison, équation du temps, angle horaire). C'est une
APPROXIMATION : précision annoncée de l'ordre de la minute aux latitudes
tempérées, qui se dégrade vers les latitudes polaires (le soleil rase l'horizon,
quelques minutes d'écart d'horaire pour une fraction de degré d'altitude). La
réfraction n'est prise en compte que par la convention de l'horizon
(`SUNRISE_ZENITH_DEG` = 90,833° : rayon solaire 0,267° + réfraction moyenne 0,566°)
— pas de modèle atmosphérique local (pression, température, relief).

Le crépuscule civil est l'instant où le centre du soleil est à 6° sous l'horizon
(`CIVIL_TWILIGHT_DEG`, définition conventionnelle). C'est la limite retenue ici
pour « il fait nuit » : approximation du projet (à l'aube/au crépuscule civil, la
lumière naturelle suffit souvent à courir sur sentier dégagé, mais plus en forêt
ou par temps couvert — la frontale reste à prévoir un peu avant).

## Fuseau horaire

Les fonctions « UTC » ne connaissent pas les fuseaux ; `local_sun_times` et
l'appelant (`arc_race_pacing`) convertissent avec `zoneinfo` (stdlib, base IANA
du système — peut être absente sur une machine sans `tzdata`, auquel cas
`ZoneInfoNotFoundError` est remontée telle quelle par `resolve_timezone`).

## Cas polaires

Quand le soleil ne franchit pas l'altitude visée un jour donné (jour polaire /
nuit polaire, ou nuit blanche pour le crépuscule civil), l'événement est `None`
et `polar` vaut `"polar_day"` ou `"polar_night"` — jamais une heure inventée.
`NightMask` (utilisé par le pacing) est basé sur l'altitude solaire minute par
minute, donc robuste à ces cas : une nuit blanche donne zéro nuit, une nuit
polaire donne de la nuit en continu.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

# Zénith (degrés) du lever/coucher « officiel » : 90° + rayon apparent du soleil
# (0,267°) + réfraction atmosphérique moyenne à l'horizon (0,566°) — convention
# NOAA. Approximation : la réfraction réelle varie avec la pression/température.
SUNRISE_ZENITH_DEG = 90.833
# Crépuscule civil : centre du soleil à 6° sous l'horizon géométrique.
CIVIL_ZENITH_DEG = 96.0
CIVIL_TWILIGHT_DEG = -6.0  # altitude du soleil à partir de laquelle il fait « nuit »

_J2000 = 2451545.0


def julian_day(when_utc: datetime) -> float:
    """Jour julien d'un instant UTC (datetime conscient ou naïf supposé UTC)."""
    if when_utc.tzinfo is not None:
        when_utc = when_utc.astimezone(timezone.utc)
    y, m = when_utc.year, when_utc.month
    d = when_utc.day + (when_utc.hour + (when_utc.minute + (when_utc.second + when_utc.microsecond / 1e6) / 60.0) / 60.0) / 24.0
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + b - 1524.5


def _sun_declination_eot(jd: float) -> Tuple[float, float]:
    """(déclinaison en radians, équation du temps en minutes) au jour julien `jd`."""
    t = (jd - _J2000) / 36525.0
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = math.radians(m)
    c = (math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * mr) * (0.019993 - 0.000101 * t) + math.sin(3 * mr) * 0.000289)
    true_long = l0 + c
    omega = 125.04 - 1934.136 * t
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    seconds = 21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))
    mean_obliq = 23.0 + (26.0 + seconds / 60.0) / 60.0
    obliq = mean_obliq + 0.00256 * math.cos(math.radians(omega))
    decl = math.asin(math.sin(math.radians(obliq)) * math.sin(math.radians(app_long)))
    y = math.tan(math.radians(obliq) / 2.0) ** 2
    l0r = math.radians(l0)
    eot = 4.0 * math.degrees(
        y * math.sin(2 * l0r) - 2 * e * math.sin(mr) + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr))
    return decl, eot


def solar_altitude_deg(when_utc: datetime, lat: float, lon: float) -> float:
    """Altitude géométrique du centre du soleil (degrés, > 0 au-dessus de l'horizon),
    sans réfraction. `lon` en degrés EST positifs."""
    if when_utc.tzinfo is None:
        when_utc = when_utc.replace(tzinfo=timezone.utc)
    when_utc = when_utc.astimezone(timezone.utc)
    decl, eot = _sun_declination_eot(julian_day(when_utc))
    minutes = when_utc.hour * 60.0 + when_utc.minute + when_utc.second / 60.0 + when_utc.microsecond / 6e7
    hour_angle = math.radians((minutes + eot + 4.0 * lon - 720.0) / 4.0)
    latr = math.radians(lat)
    sin_alt = math.sin(latr) * math.sin(decl) + math.cos(latr) * math.cos(decl) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))


def _midnight_utc(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _event_minutes(day: date, lat: float, lon: float, zenith_deg: float, rising: bool
                    ) -> Tuple[Optional[float], Optional[str]]:
    """Minutes UTC (depuis 00:00 UTC de `day`) de l'événement `zenith_deg`, ou
    `(None, "never"|"always")` si le soleil ne descend jamais / ne remonte jamais
    sous ce zénith ce jour-là (cas polaires)."""
    midnight = _midnight_utc(day)
    t = 720.0 - 4.0 * lon
    latr = math.radians(lat)
    for _ in range(3):  # la déclinaison/EoT varient avec l'heure : 3 passes suffisent à la minute
        jd = julian_day(midnight + timedelta(minutes=t))
        decl, eot = _sun_declination_eot(jd)
        cos_ha = (math.cos(math.radians(zenith_deg)) / (math.cos(latr) * math.cos(decl))
                  - math.tan(latr) * math.tan(decl))
        if cos_ha > 1.0:
            return None, "never"    # le soleil n'atteint jamais cette altitude (reste dessous)
        if cos_ha < -1.0:
            return None, "always"   # le soleil reste toujours au-dessus
        ha_deg = math.degrees(math.acos(cos_ha))
        noon = 720.0 - 4.0 * lon - eot
        t = noon - 4.0 * ha_deg if rising else noon + 4.0 * ha_deg
    return t, None


def sun_times(day: date, lat: float, lon: float) -> Dict[str, object]:
    """Événements solaires de la « journée solaire » `day` (centrée sur le midi solaire
    de la longitude `lon`, `lon` en degrés EST positifs) : `civil_dawn`, `sunrise`,
    `solar_noon`, `sunset`, `civil_dusk` (datetimes UTC conscients, `None` si absent)
    et `polar` (`None`, `"polar_day"` ou `"polar_night"`, d'après l'horizon officiel).

    Pour retrouver les événements d'une DATE LOCALE, utiliser `local_sun_times`."""
    midnight = _midnight_utc(day)

    def at(minutes: Optional[float]) -> Optional[datetime]:
        return None if minutes is None else midnight + timedelta(minutes=minutes)

    rise, rise_state = _event_minutes(day, lat, lon, SUNRISE_ZENITH_DEG, True)
    sset, _ = _event_minutes(day, lat, lon, SUNRISE_ZENITH_DEG, False)
    dawn, _ = _event_minutes(day, lat, lon, CIVIL_ZENITH_DEG, True)
    dusk, _ = _event_minutes(day, lat, lon, CIVIL_ZENITH_DEG, False)
    _, eot = _sun_declination_eot(julian_day(midnight + timedelta(minutes=720.0 - 4.0 * lon)))
    polar = None
    if rise is None:
        polar = "polar_night" if rise_state == "never" else "polar_day"
    return {
        "civil_dawn": at(dawn), "sunrise": at(rise), "solar_noon": at(720.0 - 4.0 * lon - eot),
        "sunset": at(sset), "civil_dusk": at(dusk), "polar": polar,
    }


def resolve_timezone(name: str):
    """`zoneinfo.ZoneInfo(name)` ; `ValueError` au message clair si le nom IANA est
    inconnu ou si la base de fuseaux est absente."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError(f"fuseau horaire IANA inconnu ou base tz absente : « {name} » "
                         "(exemple : Europe/Paris)") from exc


def local_sun_times(day: date, lat: float, lon: float, tz) -> Dict[str, object]:
    """Événements de la DATE LOCALE `day` dans le fuseau `tz` (objet `tzinfo` ou nom
    IANA) : mêmes clés que `sun_times`, valeurs converties en heure locale. Un
    événement absent ce jour-là (cas polaire) reste `None`."""
    zone = resolve_timezone(tz) if isinstance(tz, str) else tz
    out: Dict[str, object] = {"civil_dawn": None, "sunrise": None, "solar_noon": None,
                              "sunset": None, "civil_dusk": None, "polar": None}
    for offset in (-1, 0, 1):
        events = sun_times(day + timedelta(days=offset), lat, lon)
        if offset == 0:
            out["polar"] = events["polar"]
        for key in ("civil_dawn", "sunrise", "solar_noon", "sunset", "civil_dusk"):
            value = events[key]
            if value is None:
                continue
            local = value.astimezone(zone)
            if local.date() == day:
                out[key] = local
    return out


class NightMask:
    """Masque « il fait nuit » (soleil à plus de 6° sous l'horizon) sur
    `[start_utc, end_utc]`, échantillonné à `step_s` secondes — robuste aux cas
    polaires. Les durées de nuit sont exactes au pas d'échantillonnage près (60 s
    par défaut, bien sous la précision de l'algorithme)."""

    def __init__(self, start_utc: datetime, end_utc: datetime, lat: float, lon: float, *,
                 step_s: int = 60, threshold_deg: float = CIVIL_TWILIGHT_DEG):
        if end_utc < start_utc:
            raise ValueError("NightMask : fin avant début")
        self.start = start_utc.astimezone(timezone.utc)
        self.step_s = step_s
        n = int(math.ceil((end_utc - start_utc).total_seconds() / step_s)) + 1
        # Échantillon k = altitude au CENTRE de l'intervalle [k, k+1[ (meilleure estimation
        # de l'état moyen de la minute que l'extrémité gauche).
        self._night = []
        for k in range(n):
            mid = self.start + timedelta(seconds=(k + 0.5) * step_s)
            self._night.append(solar_altitude_deg(mid, lat, lon) < threshold_deg)
        self._prefix: List[float] = [0.0]
        for flag in self._night:
            self._prefix.append(self._prefix[-1] + (step_s if flag else 0.0))

    def _cum(self, offset_s: float) -> float:
        """Secondes de nuit entre le début du masque et `offset_s` (hors masque : borné)."""
        if offset_s <= 0:
            return 0.0
        k = int(offset_s // self.step_s)
        if k >= len(self._night):
            return self._prefix[-1]
        frac = offset_s - k * self.step_s
        return self._prefix[k] + (frac if self._night[k] else 0.0)

    def night_seconds(self, t0: datetime, t1: datetime) -> float:
        """Secondes de nuit dans `[t0, t1]` (datetimes conscients)."""
        a = (t0 - self.start).total_seconds()
        b = (t1 - self.start).total_seconds()
        if b <= a:
            return 0.0
        return self._cum(b) - self._cum(a)

    def night_windows(self, t0: datetime, t1: datetime) -> List[Tuple[datetime, datetime]]:
        """Intervalles de nuit contigus dans `[t0, t1]`, bornés à `[t0, t1]`."""
        a = max(0.0, (t0 - self.start).total_seconds())
        b = (t1 - self.start).total_seconds()
        windows: List[Tuple[float, float]] = []
        k = int(a // self.step_s)
        while k * self.step_s < b and k < len(self._night):
            if self._night[k]:
                lo = max(a, k * self.step_s)
                hi = min(b, (k + 1) * self.step_s)
                if windows and abs(windows[-1][1] - lo) < 1e-9:
                    windows[-1] = (windows[-1][0], hi)
                else:
                    windows.append((lo, hi))
            k += 1
        return [(self.start + timedelta(seconds=lo), self.start + timedelta(seconds=hi)) for lo, hi in windows]
