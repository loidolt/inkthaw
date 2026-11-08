"""rebind: turn scanned PDFs into clean, reflowable EPUBs."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    __version__ = _version("rebind")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0"
