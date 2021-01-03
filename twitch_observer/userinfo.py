import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    import stream


@dataclass
class User:
    """Registered user description"""

    name: str
    chat_id: int
    streamers: Dict[str, 'stream.StreamSession']
    hooks: Dict[str, str]
    threshold: float = 0.5
    start_lock: asyncio.Lock = asyncio.Lock()
