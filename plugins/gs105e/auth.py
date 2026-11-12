"""Login hash of the GS105Ev2 web interface.

The switch's ``login.js`` merges the password with the page's random number by
interleaving their characters, then sends the MD5 of the result. The algorithm
follows py-netgear-plus (Apache-2.0) and the switch's own ``login.js``.
"""

from __future__ import annotations

import hashlib
from itertools import zip_longest


def merge(a: str, b: str) -> str:
    """Interleave the characters of ``a`` and ``b``; the longer one's tail is appended."""
    return "".join(x + y for x, y in zip_longest(a, b, fillvalue=""))


def login_hash(password: str, rand: str) -> str:
    """The value the login form posts instead of the password."""
    return hashlib.md5(merge(password, rand).encode("utf-8")).hexdigest()
