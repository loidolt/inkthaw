class InkthawError(Exception):
    """An expected failure with a message fit to show the user (no traceback)."""


class ToolMissingError(InkthawError):
    pass


class StageError(InkthawError):
    pass
