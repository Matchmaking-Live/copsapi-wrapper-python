from __future__ import annotations

import re
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "copsapi"
SOURCE = PACKAGE / "_async_client.py"
TARGET = PACKAGE / "_sync_client.py"

REPLACEMENTS: list[tuple[str, str]] = [
    (r"from \._io_async import", "from ._io_sync import"),
    (r"AsyncIterator, Awaitable, ", "Iterator, "),
    (r"Awaitable\[(\w+)\]", r"\1"),
    (r"\bAsync([A-Z]\w*)", r"\1"),
    (r"\basync def ", "def "),
    (r"\basync for ", "for "),
    (r"\basync with ", "with "),
    (r"\bawait ", ""),
    (r"__aenter__", "__enter__"),
    (r"__aexit__", "__exit__"),
    (r"\baclose\b", "close"),
]


def render() -> str:
    text = SOURCE.read_text(encoding="utf-8")
    for pattern, replacement in REPLACEMENTS:
        text = re.sub(pattern, replacement, text)
    return text


def main() -> int:
    output = render()
    if "--check" in sys.argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != output:
            print("_sync_client.py is out of date: run python scripts/generate_sync.py")
            return 1
        return 0
    TARGET.write_text(output, encoding="utf-8", newline="\n")
    print(f"Wrote {TARGET.relative_to(PACKAGE.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
