"""Backward-compatibility re-exports for ``ctdcast.converters``.

The implementation has moved:

* ``CtdBackend``, ``_SeasenselibBackend``, ``get_ctd_backend``, ``stage1``
  → :mod:`ctdcast.processors.stage1`
* ``build_profiles`` and its private helpers
  → :mod:`ctdcast.processors.profiles`

``convert_ctd_files`` is an alias for ``stage1`` kept for callers that have
not yet been updated (``cli/convert.py``, ``cli/draft.py``).
"""

from __future__ import annotations

from ctdcast.processors.profiles import (  # noqa: F401
    _select_cast_files,
    build_profiles,
)
from ctdcast.processors.stage1 import (  # noqa: F401
    CtdBackend,
    _SeasenselibBackend,
    get_ctd_backend,
    stage1,
)

convert_ctd_files = stage1
