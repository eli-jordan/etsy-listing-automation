"""The outside world: one subpackage per API this tool talks to, each with
narrow ``Protocol``s returning pydantic models, an HTTP implementation and an
in-memory fake.

Exports nothing itself: import from the API's own package.
"""
