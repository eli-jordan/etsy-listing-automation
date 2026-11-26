"""The workspace HTTP surface: the app factory and its routers.

Nothing is re-exported: :func:`etsy_listings.server.api.app.create_app` is the
application interface, and re-exporting it would make importing any
``server.api`` module load the whole app.

Every path comes from ``Workspace``: template names, colours and design ids
arrive from URLs, and the workspace's accessors are what keep them inside the
root.
"""
