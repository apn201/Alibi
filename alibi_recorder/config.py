"""One config file (TOML, optional), env overrides on top. No secrets exist here.

Lookup: --config PATH, else $ALIBI_CONFIG, else ./alibi-recorder.toml if present.
Every key can be overridden by ALIBI_<KEY> (upper case), e.g. ALIBI_DATA_DIR=/data/ais.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

from . import APP_NAME


@dataclass
class Config:
    data_dir: str = "data/ais"
    context_dir: str = "data/context"  # context recorder (alibi_recorder/context.py)
    mqtt_host: str = "meri.digitraffic.fi"
    mqtt_port: int = 443
    mqtt_path: str = "/mqtt"
    mqtt_topic: str = "vessels-v2/#"
    rest_base: str = "https://meri.digitraffic.fi/api/ais/v1"
    app_name: str = APP_NAME
    stale_s: float = 120.0  # no message of any kind while connected -> force reconnect
    connect_timeout_s: float = 30.0
    backoff_min_s: float = 1.0
    backoff_max_s: float = 60.0
    # Digitraffic: MQTT max 5 connections / min / IP. Stay under it.
    max_connects_per_min: int = 4
    fallback_after_s: float = 300.0  # MQTT down this long -> poll REST
    # Digitraffic: V1 REST max 60 req / min / IP, responses cached ~1 min. Polling faster gains nothing.
    fallback_poll_s: float = 60.0
    flush_s: float = 1.0  # flush to the OS
    fsync_s: float = 5.0  # force to disk: a power cut costs seconds
    stats_s: float = 60.0
    disk_warn_gb: float = 5.0
    disk_stop_gb: float = 1.0

    @property
    def root(self) -> Path:
        return Path(self.data_dir)


def load_config(path: str | None = None) -> Config:
    cfg = Config()
    path = path or os.environ.get("ALIBI_CONFIG")
    if path is None and Path("alibi-recorder.toml").is_file():
        path = "alibi-recorder.toml"
    values: dict = {}
    if path:
        with open(path, "rb") as fh:
            values.update(tomllib.load(fh))
    for f in fields(Config):
        env = os.environ.get(f"ALIBI_{f.name.upper()}")
        if env is not None:
            values[f.name] = env
    for f in fields(Config):
        if f.name in values:
            kind = type(getattr(cfg, f.name))
            setattr(cfg, f.name, kind(values[f.name]))
    unknown = set(values) - {f.name for f in fields(Config)}
    if unknown:
        raise ValueError(f"unknown config keys: {sorted(unknown)}")
    return cfg
