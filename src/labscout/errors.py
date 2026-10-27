"""Errors the user can act on, as opposed to a source being down."""


class SearchError(ValueError):
    """The search cannot run as given: a query a source rejects, or an unknown source name."""
