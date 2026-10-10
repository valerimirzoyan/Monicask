from __future__ import annotations

import re

DIGITS = re.compile(r"\D")


def normalize(number: str | None) -> str:
    return DIGITS.sub("", number or "")


def match(candidate: str | None, other: str | None) -> bool:
    a = normalize(candidate)
    b = normalize(other)
    if not a or not b:
        return False
    length = min(len(a), len(b), 11)
    return a[-length:] == b[-length:]
