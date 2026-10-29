# %% [markdown]
# # Alibi lab 02: ship profiles - prototype, own history, current journey
#
# Design (Juha, 2026-10-05):
# - **Prototypes** are templates per ship class (type group x length class). Every ship has one.
# - **Frequent ships** get their own profile; it is primary, the prototype secondary.
# - **Ships never seen before** are linked to their prototype so there is something to
#   compare with, but their own history *from the same journey* is primary.
#
# Code: `alibi_lab/profiles.py`. Fit on the first 60 % of the recording, test on the rest.
# Numbers in text cells are from the 2026-10-05 run; outputs are always current.

# %%
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from alibi_lab import profiles as P
from alibi_lab.load import ROOT, load, vessels

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 20)
plt.rcParams.update({"figure.dpi": 110, "axes.grid": True, "grid.alpha": 0.3})

loc, meta = load()
ves = vessels(meta)
classes = P.ship_class(ves)
segs = P.segments(loc)
split = int(loc["time"].min() + 0.6 * (loc["time"].max() - loc["time"].min()))
store = P.ProfileStore.fit(segs, classes, until=split)
hours = (loc["time"].max() - loc["time"].min()) / 3600
print(f"{hours:.1f} h of data, {len(segs)} moving segments ({segs['minutes'].sum() / 60:.0f} ship-hours)")
print(f"fit on the first {0.6 * hours:.1f} h, test on the last {0.4 * hours:.1f} h")

# %% [markdown]
# ## Prototypes (the templates)
# Hours = moving hours behind each template. `group/*` and `*/*` are fallbacks for classes
# with under 3 h of data. Spread = p90 - p10 across segments.

# %%
rows = []
for k, p in sorted(store.prototypes.items(), key=lambda kv: -kv[1].hours):
    rows.append({"prototype": k, "hours": p.hours, "segments": p.segments,
                 **{f: p.value.get(f) for f in P.FEATURES},
                 "speed_spread": p.spread.get("speed")})
protos = pd.DataFrame(rows)
protos.round(2).head(25)

# %%
tiers = pd.Series({m: store.tier(m) for m in segs["mmsi"].unique()}).value_counts()
print("ships by tier at the split (frequent = own >= 6 moving hours):", tiers.to_dict())
own_hours = pd.Series({m: p.hours for m, p in store.vessels.items()})
fig, ax = plt.subplots(figsize=(8, 3))
ax.hist(own_hours.clip(upper=20), bins=40)
ax.axvline(P.FREQUENT_HOURS, color="k", ls="--")
ax.set_title("Own moving hours per ship before the split (clipped at 20)")
plt.show()

# %% [markdown]
# ## Test 1: predict the next 30 minutes
# Walk every later journey as if live; every 20 min predict the next 30 min of each feature.
# Median absolute error per strategy:

# %%
_, ev = P.evaluate(loc, segs, classes, split)
strat = ["proto", "own", "history", "journey", "blend"]
err = ev.assign(**{s: (ev[s] - ev["target"]).abs() for s in strat})
print("checkpoints:", len(ev[ev["feature"] == "speed"]), "ships:", ev.groupby("tier")["mmsi"].nunique().to_dict())
err.groupby(["feature", "tier"])[strat].median().round(2)

# %% [markdown]
# For the next half hour, "carry on as you were" (journey) wins everywhere: speed is very
# persistent. That is the wrong yardstick for Alibi, which must notice when a ship *stops*
# behaving normally - and a baseline that follows the ship also follows its anomaly.

# %% [markdown]
# ## Test 2: does it notice a ship that slows down and stays slow?
# Same later journeys, twice: as recorded, and with speed x 0.4 from minute 40 on (the
# dragging-anchor pattern). Each strategy runs as a live `JourneyTracker`, 10-min windows,
# flag when a window's median speed < 0.7 x expected.
# *Absorbing* learns every window; *frozen* does not learn a window in which the ship
# departs from its own journey so far.

# %%
st = P.slowdown_test(loc, store, segs, split)
normal, slow = st[st["case"] == "normal"], st[st["case"] == "slowdown"]
print("false alarm rate on the real tracks")
display(normal.pivot_table(index="tier", columns="strategy", values="flagged", aggfunc="mean").round(2))
print("detection rate of the slowdown")
display(slow.pivot_table(index="tier", columns="strategy", values="flagged", aggfunc="mean").round(2))

# %%
fig, ax = plt.subplots(figsize=(10, 4.5))
bins = np.arange(0, slow["since_onset_min"].max() + 10, 10)
for k, g in slow.groupby("strategy"):
    r = g.groupby(pd.cut(g["since_onset_min"], bins), observed=True)["flagged"].mean()
    ax.plot(bins[:-1][: len(r)], r.to_numpy(), marker="o", ms=3,
            ls="--" if "absorbing" in k else "-", label=k)
ax.set_xlim(0, 240)
ax.set_xlabel("minutes since the slowdown began")
ax.set_ylabel("share flagged")
ax.set_title("Still noticed? Synthetic lasting slowdown (speed x 0.4)")
ax.legend()
plt.show()

# %%
normal = normal.assign(group=normal["mmsi"].map(classes).str.split("/").str[0])
(normal[normal["strategy"] == "blend (frozen)"]
 .groupby("group").agg(windows=("flagged", "size"), ships=("mmsi", "nunique"), false_alarm=("flagged", "mean"))
 .sort_values("windows", ascending=False).round(2))

# %% [markdown]
# ## Save the templates
# Prototypes and own profiles as JSON, fitted on all data so far. Derived and disposable:
# re-fit as data grows. Constants are saved with them so a template says how it was made.

# %%
full = P.ProfileStore.fit(segs, classes)
out = ROOT / "data" / "derived" / "profiles" / f"profiles-{pd.Timestamp(loc['time'].max(), unit='s'):%Y%m%d-%H}.json"
full.save(out)
print(f"{out.relative_to(ROOT)}: {len(full.prototypes)} prototypes, {len(full.vessels)} own profiles, "
      f"{sum(p.hours >= P.FREQUENT_HOURS for p in full.vessels.values())} of them frequent")

# %% [markdown]
# ## What this says (2026-10-05, ~23 h of data)
#
# - **The hierarchy holds, with one rule added: don't learn from what you flag.** The final
#   tracker (blend, frozen) keeps 97-100 % of a lasting slowdown flagged hours later, at 4 %
#   false alarms for new and frequent ships. A journey-only baseline forgets the slowdown
#   within the hour (12 % still flagged at 30-60 min); prototype-only catches it but
#   flags 14-29 % of normal windows.
# - **Report and learn are separate decisions.** Flags compare with the whole blend; learning
#   stops only when the ship departs from its own journey. Freezing on any flag locked a
#   single early class-level false alarm in for the whole journey.
# - **New ships: prototype is a cold start.** Their journey takes over within the hour.
#   Frequent ships: own profile capped in charge, journey weighted low (a ferry's first
#   minutes are port departure, not cruise).
# - **Remaining noise is ships that do not cruise:** tugs, pleasure craft, small passenger
#   ferries. "Slower than expected" means nothing for them; they need behaviour-specific
#   prototypes (work patterns, not cruise speed).
# - **"Frequent" is still measured in hours.** With one day, a cargo ship seen once for
#   8 hours counts as frequent (197 of 443 ships). The intended meaning is *seen again
#   and again*: switch to repeat journeys on several days (e.g. >= 3 journeys on >= 2
#   days) once there are a few days of data.
# - **Not yet:** location (approaches, fairways: tiles), weather (Copernicus, during the
#   hackathon), and features beyond speed in the tracker. Thresholds and weights are first
#   guesses on one day; re-fit on more days before trusting numbers.
