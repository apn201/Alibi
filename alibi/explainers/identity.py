"""Identity context: EU designation and GUR listing, by IMO number. Shown, never scored.

Two separate kinds of listing, kept apart in the finding (`details.eu_designation`,
`details.gur_listing`) and in the sentence:
    EU designation   the EU's list of vessels under Article 3s of Council Regulation 833/2014
                     (published via the Danish Maritime Authority, 2026-07-24)
    GUR listing      Ukraine's Defence Intelligence register of vessels, via OpenSanctions.
                     A GUR listing is not an EU measure and is never called a sanction here.
Neither explains nor un-explains behaviour: status is always identity_context_only and the
finding has no effect on Unusual or Unexplained.
"""

from __future__ import annotations

import csv
import json
from functools import lru_cache

from .. import config
from .base import Context, Finding

EU_FILE = "dma_eu_designated_vessels_2026-07-24.csv"
GUR_FILE = "opensanctions_ua_war_sanctions_entities.ftm.json"


@lru_cache(maxsize=1)
def eu_list() -> dict[int, dict]:
    out = {}
    path = config.SANCTIONS / EU_FILE
    if not path.exists():
        return out
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh, delimiter=";"):
            if len(row) < 4 or not row[1].strip().isdigit():
                continue
            out[int(row[1].strip())] = {"name": row[0].strip(), "date_of_application": row[2].strip(),
                                        "legal_basis": row[3].strip()}
    return out


@lru_cache(maxsize=1)
def gur_list() -> dict[int, dict]:
    out = {}
    path = config.SANCTIONS / GUR_FILE
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if '"schema":"Vessel"' not in line:
                continue
            d = json.loads(line)
            p = d.get("properties", {})
            for imo in p.get("imoNumber", []):
                digits = "".join(ch for ch in imo if ch.isdigit())
                if len(digits) == 7:
                    out[int(digits)] = {"name": (p.get("name") or [None])[0], "first_seen": d.get("first_seen"),
                                        "program": (p.get("programId") or [None])[0],
                                        "source_url": (p.get("sourceUrl") or [None])[0], "opensanctions_id": d.get("id")}
    return out


class Identity:
    id = "identity"
    title = "Identity context: EU designation, GUR listing"
    kind = "identity"
    attribution = ("EU designations via Danish Maritime Authority list (2026-07-24); "
                   "GUR listing via OpenSanctions (CC BY-NC 4.0)")
    lamp = None

    def evaluate(self, ctx: Context) -> Finding:
        imo = ctx.vessel.get("imo")
        if not imo:
            return Finding(self.id, "identity_context_only", "No IMO number is known for this ship, so identity "
                           "lists were not checked.", details={"checked": False})
        imo = int(imo)
        eu, gur = eu_list().get(imo), gur_list().get(imo)
        parts = []
        if eu:
            parts.append(f"EU designation: listed under {eu['legal_basis']}, applied from {eu['date_of_application']}.")
        else:
            parts.append("EU designation: not on the EU list of 2026-07-24.")
        if gur:
            parts.append(f"GUR listing: on the Ukrainian Defence Intelligence (GUR) vessel register via OpenSanctions, "
                         f"first seen {str(gur['first_seen'])[:10]}.")
        else:
            parts.append("GUR listing: not on the GUR vessel register.")
        parts.append("Neither listing explains or counts against the behaviour assessed here.")
        return Finding(self.id, "identity_context_only", " ".join(parts),
                       source_reference=f"{EU_FILE}; {GUR_FILE}",
                       details={"checked": True, "imo": imo,
                                "eu_designation": {"listed": bool(eu), **(eu or {}), "list_date": "2026-07-24"},
                                "gur_listing": {"listed": bool(gur), **(gur or {})}})


EXPLAINER = Identity()
