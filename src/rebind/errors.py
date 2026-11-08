class RebindError(Exception):
    """An expected failure with a message fit to show the user (no traceback)."""


class ToolMissingError(RebindError):
    pass


class StageError(RebindError):
    pass
