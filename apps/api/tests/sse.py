"""SSE 응답 파싱 도우미."""

import json
from typing import Any


def parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in raw.strip().split("\n\n"):
        event, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if event:
            events.append((event, data or {}))
    return events


def answer_text(events: list[tuple[str, dict[str, Any]]]) -> str:
    return "".join(d["text"] for e, d in events if e == "token")
