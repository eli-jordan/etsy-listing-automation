"""Deployment runs: live plan/apply runs, in memory and forgotten on restart
(ADR-0041, ADR-0042). The engine computes every plan and executes every stage;
this package queues runs, drives the engine for them one at a time and keeps
a replayable event log. Serving that log is the server's
(``server/api/runs.py``). This package re-exports nothing, and withholds
``executor`` and ``review``: only ``deployments`` may import them (Import
Linter's ``protected`` contract).
"""
