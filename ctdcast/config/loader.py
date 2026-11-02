"""Config loading utilities for ctdcast reports."""

from __future__ import annotations

import copy
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """A YAML file ctdcast reads could not be used as written; the message says where and why."""


class _StrictLoader(yaml.SafeLoader):
    """A safe YAML loader that refuses a key repeated in one mapping.

    Plain YAML keeps the last of two equal keys and drops the first without a word, so a
    second ``steps:`` under ``data_processing:``, or two steps written as one list item, would
    silently lose everything under the first.
    """

    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool = False
    ) -> dict:  # PyYAML's signature
        seen: dict[Any, int] = {}
        for key_node, _value in node.value:
            key = self.construct_object(key_node, deep=deep)
            line = key_node.start_mark.line + 1
            if key in seen:
                raise _DuplicateKey(key, seen[key], line)
            seen[key] = line
        return super().construct_mapping(node, deep=deep)


class _DuplicateKey(yaml.YAMLError):
    def __init__(self, key: Any, first: int, second: int) -> None:  # noqa: ANN401  # any YAML key
        super().__init__(f"{key!r} at lines {first} and {second}")
        self.key, self.first, self.second = key, first, second


#: Names of processing steps, for the hint when one is repeated inside a list item.
_STEP_NAMES = {
    "wildedit",
    "alignctd",
    "celltm",
    "window_filter",
    "filter",
    "loopedit",
    "split",
    "binavg",
}


def load_yaml(path: Path | str) -> Any:  # noqa: ANN401  # whatever the file holds
    """Read a YAML file, refusing a key repeated in one mapping.

    Parameters
    ----------
    path : path-like
        The file.

    Returns
    -------
    object
        The parsed content (``None`` for an empty file).

    Raises
    ------
    ConfigError
        When the file cannot be parsed, or a key appears twice in the same block; the message
        names the file, the key and the lines, and what to change.
    FileNotFoundError
        When the file does not exist.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    try:
        return yaml.load(text, Loader=_StrictLoader)  # a SafeLoader subclass
    except _DuplicateKey as exc:
        if exc.key in _STEP_NAMES:
            hint = (
                f"If these are two {exc.key} steps, start each with '- ' on its own line so "
                "they are separate items in the steps list; written as one item, only the "
                "second would run."
            )
        else:
            hint = (
                "YAML would keep only the second and silently drop everything under the "
                f"first; merge the two {exc.key!r} blocks into one, or delete one."
            )
        msg = (
            f"{p}: {exc.key!r} appears twice in the same block, at lines {exc.first} and "
            f"{exc.second}. {hint}"
        )
        raise ConfigError(msg) from None
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        problem = getattr(exc, "problem", None) or str(exc)
        msg = f"{p}: not valid YAML{where}: {problem}"
        raise ConfigError(msg) from None


def load_config(path: Path | str) -> dict[str, Any]:
    """Read a cruise ``config.yaml``: a mapping, with no key repeated in one block.

    Parameters
    ----------
    path : path-like
        The config file.

    Returns
    -------
    dict
        The parsed config; empty for an empty file.

    Raises
    ------
    ConfigError
        As :func:`load_yaml`, or when the file is not a mapping of blocks.
    FileNotFoundError
        When the file does not exist.
    """
    data = load_yaml(path)
    if data is None:
        return {}
    if not isinstance(data, dict):
        msg = (
            f"{path}: expected blocks such as data:, output:, data_processing: at the top "
            f"level, got a {type(data).__name__}"
        )
        raise ConfigError(msg)
    return data


def warn_section_yaml_deprecated() -> None:
    """Warn that ``section_yaml`` is deprecated in favour of ``groupings_yaml``.

    The single notice for the config-key spelling and the ``report()`` / ``init`` parameter
    spelling, so every entry point that still honours ``section_yaml`` emits the same
    ``DeprecationWarning`` naming the replacement and the removal version (0.5.0).
    """
    warnings.warn(
        "`section_yaml` is deprecated and will be removed in 0.5.0; use `groupings_yaml` "
        "(the file holds both sections: and timeseries:).",
        DeprecationWarning,
        stacklevel=3,
    )


def groupings_path(data: dict[str, Any] | None) -> Path | None:
    """Return the groupings YAML named by a config ``data:`` block.

    The file defines two kinds of cast group -- ``sections:`` (transects plotted
    against distance) and ``timeseries:`` (repeat stations plotted against time)
    -- so ``groupings_yaml`` is the key, and ``ctd_groupings.yaml`` the
    conventional filename. ``section_yaml`` named only half of what the file
    does; it stays accepted, with a ``DeprecationWarning``, until 0.5.0.

    Parameters
    ----------
    data : dict or None
        The config's ``data:`` mapping.

    Returns
    -------
    Path or None
        The path, or ``None`` when neither key is set.
    """
    d = data or {}
    value = d.get("groupings_yaml")
    if value is None and d.get("section_yaml"):
        warn_section_yaml_deprecated()
        value = d.get("section_yaml")
    return Path(str(value)) if value else None


@dataclass
class SectionsConfig:
    """Parsed contents of a ``ctd_sections.yaml`` file.

    Loaded once at the ``report()`` entry point and passed to page builders,
    replacing four independent ``yaml.safe_load`` calls scattered across the
    reports package.
    """

    sections: dict[str, dict[str, Any]] = field(default_factory=dict)
    timeseries: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Values are not all strings: ``contributors`` is a list of mappings and
    # ``creator``/``embargo`` are mappings.  See ctdcast.config.people.
    cruise_info: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path | str) -> SectionsConfig:
        """Load a ``SectionsConfig`` from a ``ctd_sections.yaml`` file.

        Returns an empty ``SectionsConfig`` if the file does not exist.
        """
        p = Path(path)
        if not p.exists():
            return cls()
        data: dict[str, Any] = load_yaml(p) or {}
        return cls(
            sections=data.get("sections") or {},
            timeseries=data.get("timeseries") or {},
            cruise_info=data.get("cruise_info") or {},
        )


def load_display_config(cruise_cfg: dict[str, Any]) -> dict[str, dict]:
    """Return VARIABLES with cruise-level overrides applied.

    Package defaults come from :data:`ctdcast.config.parameters.VARIABLES`.
    Per-cruise overrides are read from ``cruise_cfg["display"]["variables"]``
    (the ``display:`` block in the cruise ``config.yaml``).  Later keys win.
    Returns a new dict; nothing global is mutated, so the result can be
    recorded in the output file's attributes for provenance.

    Example cruise config override::

        display:
          variables:
            temperature_1:
              vmin: 4
              vmax: 25
    """
    from ctdcast.config.parameters import VARIABLES

    merged: dict[str, dict] = copy.deepcopy(VARIABLES)
    overrides = (cruise_cfg.get("display") or {}).get("variables") or {}
    for name, over in overrides.items():
        merged.setdefault(name, {}).update(over)
    return merged
