"""The one definition of a sensor id's trimmed form (REQ-0069, REQ-0076).

Every comparison of sensor ids — Python's, before a write; Postgres's, against
rows already stored; the CLI's, over an export — must strip the same
characters, or an id one side considers trimmed escapes the other's check.
``str.strip()`` with no argument strips every character ``str.isspace()``
accepts (tab, newline, no-break space, the Unicode spaces …), while Postgres's
one-argument ``btrim`` strips only the ASCII space: a legacy row stored as
``"\\tSEN-1\\n"`` used to be invisible to the registry's own clash check.

So the set is spelled out once, here: Python strips exactly ``WHITESPACE`` and
the SQL side passes the same string to ``btrim(value, characters)``
(``services.sensors.trimmed_sql``). The CLI's duplicates report uses it too, so
this module imports nothing but the standard library.
"""

from __future__ import annotations

__all__ = ["WHITESPACE", "normalise_sensor_id"]

#: Every character for which ``str.isspace()`` is true — what ``str.strip()``
#: removes by default — as one string. Spelled out rather than computed so the
#: SQL side receives a fixed value; a test checks it against ``isspace``.
WHITESPACE = (
    "\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f \x85\xa0 "
    "           "
    "    　"
)


def normalise_sensor_id(value: str | None) -> str | None:
    """The stored form of a sensor id: trimmed of ``WHITESPACE``, ``None`` when blank."""
    if value is None:
        return None
    trimmed = value.strip(WHITESPACE)
    return trimmed or None
