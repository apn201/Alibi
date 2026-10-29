"""Per-vessel tracks: stops, legs between stops, ports, and how repeatable a route is.

A stop is a run of positions below MOVING_KN lasting at least STOP_MIN minutes.
A leg is the movement from the end of one stop to the start of the next, with no
reporting gap longer than MAX_GAP_MIN inside it. Stop centroids are clustered into
"ports" (radius PORT_KM), so a leg is (vessel, from port, to port, times, path).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MOVING_KN = 2.0
STOP_MIN = 10
MAX_GAP_MIN = 15
PORT_KM = 2.0
RESAMPLE = 40

# Approximate, for labels only (within 6 km). Not used in any computation.
PLACES = {
    "Helsinki": (60.160, 24.950), "Vuosaari": (60.210, 25.190), "Tallinn": (59.445, 24.765),
    "Muuga": (59.500, 24.950), "Paldiski": (59.350, 24.050), "Stockholm": (59.320, 18.100),
    "Kapellskär": (59.720, 19.070), "Turku": (60.435, 22.220), "Naantali": (60.465, 22.030),
    "Mariehamn": (60.090, 19.930), "Långnäs": (60.115, 20.300), "Hanko": (59.820, 22.970),
    "Kotka": (60.460, 26.950), "Hamina": (60.560, 27.200), "Kilpilahti": (60.300, 25.550),
    "Vaasa": (63.085, 21.570), "Holmsund": (63.700, 20.340), "Rauma": (61.130, 21.460),
    "Pori": (61.600, 21.450), "Oulu": (65.010, 25.420), "Kemi": (65.700, 24.550),
    "Inkoo": (60.040, 24.000), "Uusikaupunki": (60.800, 21.400), "Porvoo": (60.390, 25.660),
}


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def place_name(lat: float, lon: float) -> str:
    best, dist = None, 6.0
    for name, (plat, plon) in PLACES.items():
        d = float(haversine_km(lat, lon, plat, plon))
        if d < dist:
            best, dist = name, d
    return best or f"{lat:.2f}N {lon:.2f}E"


def stops_and_legs(loc: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """loc: locations sorted by mmsi, time (as from load()). Returns (stops, legs)."""
    stops, legs = [], []
    for mmsi, g in loc.dropna(subset=["lat", "lon"]).groupby("mmsi", sort=False):
        t = g["time"].to_numpy()
        lat, lon = g["lat"].to_numpy(), g["lon"].to_numpy()
        moving = (g["sog"].fillna(0).to_numpy() >= MOVING_KN)
        # runs of equal moving-state
        change = np.flatnonzero(np.diff(moving.astype(np.int8))) + 1
        bounds = np.concatenate([[0], change, [len(t)]])
        vessel_stops = []
        for a, b in zip(bounds[:-1], bounds[1:]):
            if not moving[a] and t[b - 1] - t[a] >= STOP_MIN * 60:
                vessel_stops.append((a, b))
        for (a, b) in vessel_stops:
            stops.append({"mmsi": mmsi, "t0": t[a], "t1": t[b - 1],
                          "lat": float(np.median(lat[a:b])), "lon": float(np.median(lon[a:b]))})
        for (a0, b0), (a1, b1) in zip(vessel_stops[:-1], vessel_stops[1:]):
            s, e = b0 - 1, a1  # last stopped point -> first stopped point
            if e - s < 3 or np.max(np.diff(t[s:e + 1])) > MAX_GAP_MIN * 60:
                continue
            seg_lat, seg_lon = lat[s:e + 1], lon[s:e + 1]
            step = haversine_km(seg_lat[:-1], seg_lon[:-1], seg_lat[1:], seg_lon[1:])
            legs.append({"mmsi": mmsi, "t0": t[s], "t1": t[e], "duration_min": (t[e] - t[s]) / 60,
                         "dist_km": float(step.sum()),
                         "from_lat": float(np.median(lat[a0:b0])), "from_lon": float(np.median(lon[a0:b0])),
                         "to_lat": float(np.median(lat[a1:b1])), "to_lon": float(np.median(lon[a1:b1])),
                         "path": _resample(seg_lat, seg_lon, step)})
    stops, legs = pd.DataFrame(stops), pd.DataFrame(legs)
    if len(stops):
        ports = _cluster(stops[["lat", "lon"]].to_numpy())
        stops["port"] = [ports.assign(p) for p in stops[["lat", "lon"]].to_numpy()]
    if len(legs):
        legs["from_port"] = [ports.assign(p) for p in legs[["from_lat", "from_lon"]].to_numpy()]
        legs["to_port"] = [ports.assign(p) for p in legs[["to_lat", "to_lon"]].to_numpy()]
        legs["speed_kn"] = legs["dist_km"] / (legs["duration_min"] / 60) / 1.852
        # Route = place to place: terminals of one port (Helsinki #2, #3) are one place.
        legs["from_place"] = legs["from_port"].str.replace(r" #\d+$", "", regex=True)
        legs["to_place"] = legs["to_port"].str.replace(r" #\d+$", "", regex=True)
        legs["route"] = legs["from_place"] + " -> " + legs["to_place"]
    return stops, legs


def _resample(lat, lon, step) -> np.ndarray:
    """Path as RESAMPLE points evenly spaced by distance travelled: shape (RESAMPLE, 2)."""
    cum = np.concatenate([[0.0], np.cumsum(step)])
    if cum[-1] <= 0:
        return np.column_stack([np.full(RESAMPLE, lat[0]), np.full(RESAMPLE, lon[0])])
    at = np.linspace(0, cum[-1], RESAMPLE)
    return np.column_stack([np.interp(at, cum, lat), np.interp(at, cum, lon)])


class _Ports:
    def __init__(self, centers: list[tuple[float, float]]):
        self.centers = np.array(centers)
        self.names = []
        seen: dict[str, int] = {}
        for lat, lon in centers:
            base = place_name(lat, lon)
            seen[base] = seen.get(base, 0) + 1
            self.names.append(base if seen[base] == 1 else f"{base} #{seen[base]}")

    def assign(self, p) -> str:
        d = haversine_km(p[0], p[1], self.centers[:, 0], self.centers[:, 1])
        return self.names[int(np.argmin(d))]


def _cluster(points: np.ndarray) -> _Ports:
    """Greedy: densest stops first, anything within PORT_KM of a centre joins it."""
    centers: list[tuple[float, float]] = []
    members: list[list[np.ndarray]] = []
    # order by local density so centres sit on busy berths, not on stragglers
    order = np.argsort([-np.sum(haversine_km(p[0], p[1], points[:, 0], points[:, 1]) < PORT_KM) for p in points])
    for p in points[order]:
        if centers:
            d = haversine_km(p[0], p[1], np.array(centers)[:, 0], np.array(centers)[:, 1])
            i = int(np.argmin(d))
            if d[i] < PORT_KM:
                members[i].append(p)
                continue
        centers.append((float(p[0]), float(p[1])))
        members.append([p])
    return _Ports(centers)


def route_consistency(legs: pd.DataFrame, min_legs: int = 4) -> tuple[pd.DataFrame, pd.DataFrame]:
    """For routes with >= min_legs legs: how much do legs differ from the route's median path?

    Returns (per-route summary, per-leg table with deviation_km = mean distance of the leg's
    resampled path from the route's median path)."""
    rows, per_leg = [], []
    for route, g in legs.groupby("route"):
        if len(g) < min_legs or g["from_place"].iloc[0] == g["to_place"].iloc[0]:
            continue
        paths = np.stack(g["path"].to_numpy())  # (n, RESAMPLE, 2)
        median = np.median(paths, axis=0)
        dev = haversine_km(paths[..., 0], paths[..., 1], median[None, :, 0], median[None, :, 1]).mean(axis=1)
        g = g.assign(deviation_km=dev)
        per_leg.append(g)
        within = g.groupby("mmsi")["duration_min"].std().dropna()
        rows.append({
            "route": route, "legs": len(g), "vessels": g["mmsi"].nunique(),
            "km": g["dist_km"].median(), "min_median": g["duration_min"].median(),
            "min_iqr": g["duration_min"].quantile(0.75) - g["duration_min"].quantile(0.25),
            "speed_kn": g["speed_kn"].median(),
            "dev_km_median": float(np.median(dev)), "dev_km_p90": float(np.quantile(dev, 0.9)),
            "dur_sd_within_vessel": within.mean() if len(within) else np.nan,
            "dur_sd_all": g["duration_min"].std(),
        })
    summary = pd.DataFrame(rows).sort_values("legs", ascending=False, ignore_index=True)
    return summary, (pd.concat(per_leg, ignore_index=True) if per_leg else pd.DataFrame())
