"""Durable explicit authoring jobs, independent of HTTP and CLI.

Import coordinator.Preparations for submit/status/list_jobs/cancel/events,
reconcile_saved and lifecycle start/close/recover/cleanup. Models are immutable
public request results. Store, execution and evidence are implementation details
reached only through Preparations.

previews.editor_preview is the transient editor composite, reached through
application.scene_previews, and draft_rules holds every rule a draft answers to;
neither publishes maps nor invokes models. activity scopes foreground priority
to a workspace.
"""
