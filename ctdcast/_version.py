"""Package version, resolved from installed metadata."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__: str = _pkg_version("ctdcast")
except PackageNotFoundError:
    __version__ = "0.1.0.dev0"
