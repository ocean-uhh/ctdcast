"""Hidden deprecated-flag aliases shared across the CLI verbs.

A renamed flag keeps its old spelling as a hidden alias for one release: the alias
sets the canonical destination and records that the deprecated spelling was used, so
the verb's ``run()`` can warn once via :func:`warn_deprecated`.  argparse cannot
natively report which of several option strings sharing a destination was typed, so
the alias needs its own action.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from typing import Any

#: Deprecated flag spelling -> its canonical replacement, for the warning message.
DEPRECATED_FLAGS: dict[str, str] = {
    "--stations": "--casts",
    "--cast": "--only",
}


class DeprecatedAlias(argparse.Action):
    """Set the canonical destination and record the deprecated spelling used."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,  # noqa: ARG002  (argparse Action interface)
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        """Store *values* on the canonical dest and note the deprecated *option_string*."""
        used = getattr(namespace, "deprecated_flags", None)
        if used is None:
            used = []
            namespace.deprecated_flags = used
        if option_string is not None:
            used.append(option_string)
        # nargs == 0 is the store_true-style alias; otherwise forward the parsed values.
        setattr(namespace, self.dest, True if self.nargs == 0 else values)


def warn_deprecated(args: argparse.Namespace) -> None:
    """Emit a deprecation warning for each deprecated flag spelling used on this call."""
    for opt in getattr(args, "deprecated_flags", None) or []:
        repl = DEPRECATED_FLAGS.get(opt, "the new flag")
        msg = (
            f"{opt} is deprecated and will be removed in a future release; use {repl}."
        )
        warnings.warn(msg, DeprecationWarning, stacklevel=2)
        print(f"warning: {msg}", file=sys.stderr)
