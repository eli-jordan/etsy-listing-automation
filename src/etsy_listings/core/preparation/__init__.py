"""Explicit authoring preparation, separate from CPU rendering (ADR-0053).

Import modules directly. Runtime owns global installation; worker_client owns
subprocess communication. Neither package import starts workers or loads torch.
"""
