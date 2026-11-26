"""The workspace HTTP surface: the app factory and its routers.

Nothing is re-exported, because re-exporting ``create_app`` would make importing
any ``server.api`` module load the whole app."""
