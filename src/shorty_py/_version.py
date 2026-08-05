"""Single source of truth for the SDK version.

Read by hatchling at build time (``[tool.hatch.version]``) and by the transport
when it builds the ``User-Agent``, so the published version and the version the
server sees can never drift.
"""

from __future__ import annotations

__version__ = "0.1.0"
