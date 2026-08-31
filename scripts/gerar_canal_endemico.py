# -*- coding: utf-8 -*-
"""CLI wrapper: canal endêmico Bortman."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.canal_endemico_bortman import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
