"""Package version, resolved from installed metadata."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__: str = _pkg_version("oceancast")
except PackageNotFoundError:
    __version__ = "0.0.1"
