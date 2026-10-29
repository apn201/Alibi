# %% [markdown]
# # Alibi lab 03: a real anchor drag - Eagle S, 25 December 2024
#
# Third-party data, not ours to publish (git-ignored under `data/external/eagle_s/`):
# - `eagle_s_voyage_ais.csv` and `eagle_s_technical_report_v4.pdf` from eagles-report.com.
#
# Ground truth from the report (UTC): sea passage at ~12 kn from about 03:30; **10:13 speed
# starts to drop** (port anchor dragging on a mud/clay bottom, 40-50 m); **10:26 Estlink 2**
# crossed and offline; more cables and pipelines until 10:51; 11:05 engine rpm drops;
# 11:49 engine stopped, drifting. Weather per the report: SW 4-5 rising to W 6, 2-2.5 m seas.
#
# Question: given the profiles from lab 02 (fitted on our own recording, which has never
# seen Eagle S), when would the journey tracker have flagged it, and at what false-alarm cost?

# %%
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from alibi_lab import profiles as P
from alibi_lab import tracks
from alibi_lab.external import eagle_s, events_epoch
from alibi_lab.load import load, vessels

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
plt.rcParams.update({"figure.dpi": 110, "axes.grid": True, "grid.alpha": 0.3})

EAGLE = 518998865
ev = events_epoch()
onset = ev["speed starts to drop (anchor dragging)"]
e = eagle_s()
day = e[(e["time"] >= ev["departed Ust-Luga"]) & (e["time"] < ev["engine stopped, drifting"] + 3600)]
print(f"Eagle S track: {len(e)} positions {e['ts'].min():%d.%m %H:%M} .. {e['ts'].max():%d.%m %H:%M} UTC; "
      f"length {e['length'].iloc[0]:.0f} m; 25.12 voyage: {len(day)} positions")

# %%
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 5), gridspec_kw={"width_ratios": [1.2, 1]})
sc = ax1.scatter(day["lon"], day["lat"], c=day["sog"], s=4, cmap="viridis_r", vmin=0, vmax=13)
for name, t in ev.items():
    p = day.iloc[(day["time"] - t).abs().argmin()]
    ax1.plot(p["lon"], p["lat"], "rx")
    ax1.annotate(name.split(" (")[0], (p["lon"], p["lat"]), fontsize=7, xytext=(4, 4), textcoords="offset points")
ax1.set_aspect(1 / np.cos(np.radians(60)))
fig.colorbar(sc, ax=ax1, label="sog kn")
ax1.set_title("25.12.2024 voyage, coloured by speed")
ax2.plot(day["ts"], day["sog"], lw=0.6)
for name, t in ev.items():
    ax2.axvline(pd.Timestamp(t, unit="s", tz="UTC"), color="r", lw=0.8, ls=":")
ax2.set_ylim(0, 14)
ax2.set_title("Speed over ground; red: report events")
ax2.tick_params(axis="x", rotation=45)
plt.tight_layout()
plt.show()

# %% [markdown]
# Speed is the whole signature. A steady 11.8-12.4 kn for six and a half hours, then ~9 kn
# within 15 minutes (x0.75), engine power unchanged until 11:05. Heading vs course (crab
# angle) shows nothing during the drag. The weather the report describes costs a few tenths
# of a knot at most (the report's own AIS reading: 12 -> 11.7-11.8 kn as it worsened):
# **the sea does not explain this slowdown** - which is the question Alibi asks.

# %% [markdown]
# ## Replay: profiles from our recording, Eagle S as a ship never seen before
# Eagle S gets the `tanker/XL` prototype (tanker, over 200 m). Two "too slow" rules:
# - **x0.7**: below 0.7 x expected (lab 02's rule).
# - **4 sigma & x0.9**: either below 0.7 x, or 4 x the ship's own window-to-window
#   steadiness on this journey *and* at least 10 % slower.

# %%
loc, meta = load()
classes = P.ship_class(vessels(meta))
segs = P.segments(loc)
store = P.ProfileStore.fit(segs, classes)
store.vessel_class[EAGLE] = "tanker/XL"
proto = store.prototype_for(EAGLE)
print(f"prototype {proto.key}: {proto.value['speed']:.1f} kn typical, from {proto.hours:.0f} h of our data")

rules = {"x0.7": dict(flag_below=0.7), "4 sigma & x0.9": dict(flag_below=0.7, k_sigma=4.0, and_below=0.9)}
rp = P.replay(e, store, EAGLE, rules, start=ev["departed Ust-Luga"] + 2 * 3600, end=ev["engine stopped, drifting"])
rp["ts"] = pd.to_datetime(rp["t"] + 300, unit="s", utc=True)  # window centre

fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
for ax, (k, g) in zip(axes, rp.groupby("strategy", sort=False)):
    ax.plot(g["ts"], g["observed"], "k.-", lw=0.8, label="observed (10-min median)")
    ax.plot(g["ts"], g["expected"], "b-", lw=1.2, label="expected")
    f = g[g["flagged"]]
    ax.scatter(f["ts"], f["observed"], s=60, facecolors="none", edgecolors="r", label="flagged")
    for name, t in ev.items():
        ax.axvline(pd.Timestamp(t, unit="s", tz="UTC"), color="r", lw=0.6, ls=":")
    first = g[(g["t"] >= onset - 600) & g["flagged"]]["t"].min()
    lag = (first + 600 - onset) / 60
    ax.set_title(f"{k}: first flag {lag:+.0f} min after the drag began (Estlink 2 at +13 min)")
    ax.set_ylim(0, 14)
    ax.legend(loc="lower left", fontsize=8)
plt.tight_layout()
plt.show()

# %% [markdown]
# ## The price: false alarms on our own recording
# Same rules on lab 02's tests (fit on the first 60 % of our recording, judge the rest):
# false alarms on the real tracks, by distance from the nearest place ships stop; detection
# of synthetic lasting slowdowns, strong (x0.4) and Eagle-S-like (x0.75).

# %%
split = int(loc["time"].min() + 0.6 * (loc["time"].max() - loc["time"].min()))
fit60 = P.ProfileStore.fit(segs, classes, until=split)
strategies = {k: dict(use_own=True, **kw) for k, kw in rules.items()}
out = []
for factor in (0.4, 0.75):
    st = P.slowdown_test(loc, fit60, segs, split, factor=factor, strategies=strategies)
    out.append(st.assign(factor=factor))
st = pd.concat(out, ignore_index=True)

stops, _ = tracks.stops_and_legs(loc)
centres = stops[["lat", "lon"]].to_numpy()
normal = st[(st["case"] == "normal") & (st["factor"] == 0.4)].copy()
dist = np.array([tracks.haversine_km(a, b, centres[:, 0], centres[:, 1]).min()
                 for a, b in normal[["lat", "lon"]].to_numpy()])
normal["where"] = pd.cut(dist, [-1, 3, 10, 1e9], labels=["< 3 km from a stop", "3-10 km", "open water > 10 km"])
normal["group"] = normal["mmsi"].map(classes).str.split("/").str[0]
cruising = normal[normal["group"].isin(["cargo", "tanker", "passenger"])]

summary = pd.DataFrame({
    "false alarm, all windows": normal.groupby("strategy")["flagged"].mean(),
    "false alarm, cruising ships, open water": cruising[cruising["where"] == "open water > 10 km"]
    .groupby("strategy")["flagged"].mean(),
    "detect x0.4": st[(st["case"] == "slowdown") & (st["factor"] == 0.4)].groupby("strategy")["flagged"].mean(),
    "detect x0.75": st[(st["case"] == "slowdown") & (st["factor"] == 0.75)].groupby("strategy")["flagged"].mean(),
})
lags = {}
for k, g in rp.groupby("strategy"):
    f = g[(g["t"] >= onset - 600) & g["flagged"]]
    lags[k] = (f["t"].min() + 600 - onset) / 60
summary["Eagle S: minutes to flag"] = pd.Series(lags)
summary["Eagle S: false flags in 6.5 h before"] = rp[rp["t"] < onset - 600].groupby("strategy")["flagged"].sum()
summary.round(3)

# %%
cruising.pivot_table(index="where", columns="strategy", values="flagged", aggfunc="mean", observed=True).round(3)

# %% [markdown]
# ## What this says
#
# - **A real anchor drag is gentler than our synthetic test.** Eagle S slowed to x0.75, not
#   x0.4. Lab 02's x0.7 rule flags it only after it has crossed every cable (~+67 min).
# - **Measuring the drop against the ship's own steadiness** flags it ~7 minutes after the
#   drag began, *before* Estlink 2 (+13 min), with no false flag in the 6.5 hours before.
# - **It costs false alarms**: in open water, for cargo/tanker/passenger ships, roughly 2 %
#   of 10-min windows with x0.7 against ~9 % with the sensitive rule (2026-10-05 run).
#   Near stops both rules are noisy (~20 %), which location context will explain away;
#   the open-water excess is what remains to solve.
# - **So Alibi should not be a yes/no alarm.** A graded score (how unusual for this ship,
#   how much the sea and the place explain) with a threshold the operator chooses. The
#   trade-off above is the honest curve, from one real case and one day of our data:
#   **do not tune further on Eagle S alone** - it would just fit one ship.
# - **Next evidence:** Fitburg (31.12.2025, ~130 km drag in the Gulf of Finland) is a
#   documented second case; its track is not in Digitraffic's live feed and would have to
#   come from another source. Weather (Copernicus) during the hackathon should show whether
#   "the sea explains it" removes open-water false alarms without explaining away Eagle S.
