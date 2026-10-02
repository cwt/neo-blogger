"""Thin request controllers (tech-req §3.1/§3.2): parse, authorize, render.

Blueprints are built by factory functions receiving :class:`AppContext`;
per-request state lives on Quart's ``g``.
"""
