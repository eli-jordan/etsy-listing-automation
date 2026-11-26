"""The transport-independent backend (ADR-0052).

Core never imports FastAPI, Typer, the server, the CLI or the terminal adapters
above it. Nothing is re-exported here, so importing ``etsy_listings.core`` loads
no subpackage, OpenCV or httpx.
"""
