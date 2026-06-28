"""Keloray Control — a programmable controller for Keloray / Gizwits smart lights.

Reverse-engineered, personal-use interoperability layer over the Gizwits
OpenAPI v1 that the Keloray Smart Light app uses.
"""
from .client import GizwitsClient, Device, GizwitsError, REGIONS, CANDIDATE_APP_IDS
from .effects import SceneRunner, list_scenes, get_scene
from .scheduler import Automations, Rule

__version__ = "0.1.0"
__all__ = [
    "GizwitsClient", "Device", "GizwitsError", "REGIONS", "CANDIDATE_APP_IDS",
    "SceneRunner", "list_scenes", "get_scene", "Automations", "Rule",
]
