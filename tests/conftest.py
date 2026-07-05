"""Make src/ and scripts/ importable in tests."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for sub in ("src", "scripts"):
    p = str(_ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)
