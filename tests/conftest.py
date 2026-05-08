"""Test setup: import torch before anything else to avoid the Windows DLL
conflict where pandas-first imports break torch's c10.dll loading. Then
ensure project root is importable as `src.*`."""
import torch  # noqa: F401  # MUST be before pandas / src imports

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
