"""Generator protocol shared by all synthetases."""
from __future__ import annotations

import random
from typing import List, Protocol

from ..targets import Target


class Generator(Protocol):
    name: str

    def generate(self, target: Target, k: int, rng: random.Random) -> List[str]:
        """Return k candidate RNA sequences (AUGC) for the target structure."""
        ...
