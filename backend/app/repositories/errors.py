class InvalidRepositoryUrl(Exception):
    """Clone URL failed scheme, allow-list, or resolved-address checks."""


class CloneError(Exception):
    """Clone timed out, git failed, size cap was exceeded, or inspect failed."""
