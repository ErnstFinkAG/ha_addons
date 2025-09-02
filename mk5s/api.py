from __future__ import annotations

import asyncio
from typing import Dict, List, Tuple, Optional
from aiohttp import ClientSession, ClientError

HexWord = str
Item = Tuple[int, int]  # (index, subindex)

def build_index_map(question: str) -> List[Item]:
    """Parse the baked QUESTION into an ordered list of (index, subindex) pairs."""
    items: List[Item] = []
    for i in range(0, len(question), 6):
        idx = int(question[i : i + 4], 16)
        si  = int(question[i + 4 : i + 6], 16)
        items.append((idx, si))
    return items

def parse_answers(answer: str, ordered_items: List[Item]) -> Dict[Item, Optional[HexWord]]:
    """Walk the answer string: 'X' => 1 char, else 8 hex chars."""
    result: Dict[Item, Optional[HexWord]] = {}
    p = 0
    for item in ordered_items:
        if p >= len(answer):
            result[item] = None
            continue
        if answer[p] == "X":
            result[item] = None
            p += 1
        else:
            result[item] = answer[p : p + 8]
            p += 8
    return result

def u32(hex8: str) -> int:
    return int(hex8, 16)

def u16_hi(hex8: str) -> int:
    return int(hex8[0:4], 16)

def u16_lo(hex8: str) -> int:
    return int(hex8[4:8], 16)

def decode_tracked(values: Dict[Item, Optional[HexWord]], tracked):
    out = {}
    for (item, name) in tracked:
        raw = values.get(item)
        if raw is None:
            out[name] = None
            continue
        if name == "pressure_bar":
            out[name] = u16_hi(raw) / 1000.0
        elif name in ("motorstarts", "lastspiele"):
            out[name] = float(u16_lo(raw))
        elif name.startswith("duty_"):
            out[name] = u16_hi(raw) / 10.0
        elif name == "luefterstarts":
            out[name] = float(u32(raw))
        else:
            out[name] = None
    return out

class MK5SClient:
    def __init__(self, host: str, question: str, session: ClientSession) -> None:
        self._host = host
        self._question = question
        self._session = session
        self._ordered_items = build_index_map(question)

    @property
    def ordered_items(self) -> List[Item]:
        return self._ordered_items

    async def fetch(self) -> str:
        url = f"http://{self._host}/cgi-bin/mkv.cgi"
        data = {"QUESTION": self._question}
        try:
            async with self._session.post(url, data=data, timeout=5) as resp:
                resp.raise_for_status()
                text = await resp.text()
                return text.strip()
        except (ClientError, asyncio.TimeoutError) as e:
            raise RuntimeError(f"HTTP error: {e}") from e

    async def snapshot(self):
        ans = await self.fetch()
        parsed = parse_answers(ans, self._ordered_items)
        from .const import TRACKED_ITEMS
        return decode_tracked(parsed, TRACKED_ITEMS)
