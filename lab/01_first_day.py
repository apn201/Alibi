# %% [markdown]
# # Alibi lab 01: what the first day of AIS can and cannot tell us
#
# Source: the recorder's closed hours in `data/ais` (pulled hourly from Umbrel).
# Everything here only reads them. Re-run with `python tools/run_notebook.py lab/01_first_day.py`;
# numbers in the text cells were written for the 2026-10-05 run, the outputs are always current.
#
# Questions:
# 1. Is the data clean enough to build on? (rates, gaps, sentinels, duplicates)
# 2. Vessel-specific profiles: does the same ship repeat itself on the same route?
# 3. Tile profiles: how many tiles have enough traffic, and how stable is a tile's
#    speed profile from one half of the period to the other?

# %%
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from alibi_lab import tiles, tracks
from alibi_lab.load import load, vessels

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
plt.rcParams.update({"figure.dpi": 110, "axes.grid": True, "grid.alpha": 0.3})

loc, meta = load()
ves = vessels(meta)
hours = (loc["time"].max() - loc["time"].min()) / 3600
print(f"{loc['ts'].min():%Y-%m-%d %H:%M} .. {loc['ts'].max():%Y-%m-%d %H:%M} UTC = {hours:.1f} h")
print(f"positions {len(loc):,} (duplicates removed: {loc.attrs['duplicates_removed']:,}), "
      f"metadata messages {len(meta):,}")
print(f"vessels with positions {loc['mmsi'].nunique()}, with metadata {len(ves)}")

# %% [markdown]
# ## 1. Data quality

# %%
fig, axes = plt.subplots(1, 3, figsize=(15, 3.6))
per_hour = loc.set_index("ts").resample("1h")["mmsi"].agg(["size", "nunique"])
axes[0].plot(per_hour.index, per_hour["size"] / 1000, label="positions (k)")
axes[0].plot(per_hour.index, per_hour["nunique"] / 10, label="vessels (x10)")
axes[0].set_title("Per hour")
axes[0].legend()
axes[0].tick_params(axis="x", rotation=45)

dt = loc.groupby("mmsi")["time"].diff().dropna()
axes[1].hist(dt.clip(upper=200), bins=100)
axes[1].set_yscale("log")
axes[1].set_title("Seconds between a vessel's reports (clipped at 200)")

ves["group"].value_counts().plot.barh(ax=axes[2])
axes[2].set_title("Vessels by type group")
plt.tight_layout()
plt.show()

print("report interval s, p10/p50/p90/p99:", dt.quantile([0.1, 0.5, 0.9, 0.99]).round(0).tolist())
print("gaps > 15 min inside a vessel's track:", int((dt > 900).sum()))
print("share 'not available':", loc[["sog", "cog", "heading", "rot"]].isna().mean().round(3).to_dict())
print("navStat counts:", loc["navStat"].value_counts().head(6).to_dict())

# %% [markdown]
# Where the receivers hear ships, moving positions only (sog >= 2 kn), log density:

# %%
mv = loc[loc["sog"] >= 2]
fig, ax = plt.subplots(figsize=(11, 8))
hb = ax.hexbin(mv["lon"], mv["lat"], gridsize=260, bins="log", mincnt=1, cmap="viridis")
ax.set_aspect(1 / np.cos(np.radians(60)))
ax.set_title("Moving positions, first day")
fig.colorbar(hb, ax=ax, label="positions (log)")
plt.show()

# %% [markdown]
# ## 2. Vessel-specific: does the same ship repeat itself?
#
# Stops (>= 10 min below 2 kn) and legs between them, per vessel. Stops clustered into
# places; a route is place to place. For every route with >= 4 legs: leg duration, and
# how far each leg's path strays from the route's median path.

# %%
stops, legs = tracks.stops_and_legs(loc)
summary, per_leg = tracks.route_consistency(legs, min_legs=4)
print(f"stops {len(stops)}, legs {len(legs)}, routes with >= 4 legs: {len(summary)}")
summary.round(1)

# %% [markdown]
# `dur_sd_within_vessel` vs `dur_sd_all` is the question in one pair of numbers: on
# Helsinki-Tallinn one ship repeats its crossing within a few minutes, while the fleet
# spans tens of minutes (fast and slow ships). The single-ship archipelago ferries repeat
# to the minute, except a few legs with a long SD: those are legs where the ship waited
# or loitered without a detected stop - exactly the kind of oddity Alibi should explain.

# %%
ht = per_leg[per_leg["route"].isin(["Helsinki -> Tallinn", "Tallinn -> Helsinki"])].copy()
ht["name"] = ht["mmsi"].map(ves["name"])
fig, axes = plt.subplots(1, 2, figsize=(15, 5))
for i, (name, g) in enumerate(ht.groupby("name")):
    axes[0].scatter(g["duration_min"], np.full(len(g), i), s=40)
axes[0].set_yticks(range(ht["name"].nunique()), sorted(ht["name"].unique()))
axes[0].set_xlabel("crossing minutes")
axes[0].set_title("Helsinki-Tallinn crossings per ship")
for _, leg in ht.iterrows():
    p = leg["path"]
    axes[1].plot(p[:, 1], p[:, 0], lw=1, alpha=0.7)
axes[1].set_aspect(1 / np.cos(np.radians(60)))
axes[1].set_title("Their paths")
plt.tight_layout()
plt.show()
ht.groupby("name")[["duration_min", "speed_kn", "deviation_km"]].agg(["count", "median", "std"]).round(1)

# %% [markdown]
# ## 3. Tiles: enough traffic, and stable?
#
# Grid 0.05 deg lat x 0.10 deg lon (about 5.5 km). A passage = one moving vessel's run
# through one tile. Profile per tile = distribution of passage median speeds.

# %%
pas = tiles.passages(loc)
prof = tiles.tile_profile(pas)
print(f"passages {len(pas):,} in {len(prof):,} tiles; passages per tile p50/p90/p99/max:",
      prof["passages"].quantile([0.5, 0.9, 0.99, 1.0]).round(0).tolist())

fig, ax = plt.subplots(figsize=(11, 8))
sc = ax.scatter(prof["lon"], prof["lat"], c=np.log10(prof["passages"]), s=6, marker="s", cmap="magma_r")
ax.set_aspect(1 / np.cos(np.radians(60)))
ax.set_title("Passages per tile, first day (log10)")
fig.colorbar(sc, ax=ax, label="log10 passages")
plt.show()

# %% [markdown]
# How long until tiles have enough passages, if traffic continues at today's rate
# (hackathon: about 25 days of data):

# %%
ready = pd.DataFrame({need: {f"<= {d} d": int((tiles.days_to_ready(prof, hours, need) <= d).sum())
                             for d in (1, 7, 14, 25)} for need in (10, 30, 100)})
ready.columns = [f"tiles with {n}+ passages" for n in ready.columns]
print(f"of {len(prof)} tiles seen so far")
ready

# %% [markdown]
# The honest test: learn each tile's median speed on the first half of the period,
# check it on the second half. Only tiles with enough passages on both sides.

# %%
split = loc["time"].min() + (loc["time"].max() - loc["time"].min()) / 2
rows = []
fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))
for ax, m in zip(axes, (5, 10, 20)):
    s = tiles.split_half_stability(pas, split, m)
    diff = (s["median_a"] - s["median_b"]).abs()
    rows.append({"min passages each half": m, "tiles": len(s), "corr": s["median_a"].corr(s["median_b"]),
                 "|diff| kn p50": diff.median(), "|diff| kn p90": diff.quantile(0.9)})
    ax.scatter(s["median_a"], s["median_b"], s=10, alpha=0.6)
    lim = [0, max(s["median_a"].max(), s["median_b"].max()) + 1]
    ax.plot(lim, lim, "k--", lw=0.8)
    ax.set_title(f">= {m} passages per half: {len(s)} tiles")
    ax.set_xlabel("median kn, first half")
    ax.set_ylabel("median kn, second half")
plt.tight_layout()
plt.show()
pd.DataFrame(rows).round(2)

# %% [markdown]
# ## What this says (2026-10-05, ~22 h of data)
#
# - **Data is clean enough to build on.** About 10 s between a vessel's reports, no
#   recorder gaps, sentinels are rare except heading (13 % "511") and rate of turn.
#   Ships' own tracks do have ~1,700 gaps over 15 min (leaving receiver range, moored
#   ships reporting every few minutes): track logic must split on gaps, never interpolate.
#   One tile shows a 51 kn median: an aircraft or fast craft; filter by type before profiling.
#   Digitraffic's `time` is its own receive stamp (within 1 s of ours), so it cannot
#   measure radio latency.
# - **Vessel-specific profiles look strong.** The same ship repeats its route to within
#   minutes, and its path to within a few hundred metres; differences between ships are
#   much larger. So "is this ship behaving like itself?" is a sharper question than "is
#   this ship behaving like the tile?". Needs a few days per ship to be meaningful;
#   regular ferries have it already.
# - **Tile profiles need the weeks.** Day one: only about 110 tiles have 30+ passages;
#   at this rate about 940 will by day 7 and about 1,550 (of ~2,500 seen) by day 25. Split-half medians already agree well in busy
#   tiles (corr ~0.9, typical difference under 1 kn), so the method is sound; the
#   coverage is not there yet.
# - **Weather is not testable yet.** One day, one weather situation. Get the Copernicus
#   join working now; compare calm vs windy days once there are some.
# - Next: day-of-week and ship-type splits, a per-vessel profile prototype on ferries,
#   and the Copernicus wind/wave join.
