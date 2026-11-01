"""Versioned archive of every resource in the installed client.

``scan`` extracts and records a version, ``diff`` compares any two versions and
``server`` serves the visual browser. See ``scan.py`` for the pipeline.
"""
from .catalog import CATEGORIES, KEYS, LABELS
from .store import Store

__all__ = ['CATEGORIES', 'KEYS', 'LABELS', 'Store']
