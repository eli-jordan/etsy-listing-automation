"""Explicit authoring preparation, separate from CPU rendering (ADR-0054).

Import modules directly; nothing is re-exported. Withheld: ``installation`` and
the embedded worker distribution, reached through ``runtime``, and the geometry
fitter, reached through ``numerics``. Artifact loading and numerical preparation
never depend on the installed runtime, and importing this package never starts
workers or loads torch.
"""
