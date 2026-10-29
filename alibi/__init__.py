"""ALIBI: Automatic Lookout for Irregular Baltic Itineraries.

A triage service: an upstream AIS system (or ALIBI's own reference detector) flags a
candidate event; ALIBI says how unusual it is against the ship's expected behaviour, which
evidence explains the deviation and how much remains unexplained. Unexplained is not a
claim of intent.
"""

API_VERSION = "1.0.0"
MODEL_VERSION = "alibi-0.1.0"
