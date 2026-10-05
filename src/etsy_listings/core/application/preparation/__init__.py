"""Durable explicit authoring jobs, independent of HTTP and CLI.

Import coordinator.Preparations for submit/status/list_jobs/cancel/events,
reconcile_saved and lifecycle start/close/recover/cleanup. Models are immutable
public request results. Store and execution are implementation details reached
only through Preparations. Hosts offload synchronous operations to their request
executor; neither capability inspection nor numerical work belongs on an async
HTTP event loop. start also reconciles saves interrupted before job creation.
"""
