from dataclasses import dataclass
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    import stream
    import userinfo as ui


@dataclass
class StreamFeedback:
    """Feedback from stream session to subscribers"""

    streamer_name: str
    chat_message: 'stream.ChatMessage'
    subscribers: List['stream.Subscribe']


@dataclass
class MatcherFeedback:
    """Feedback from matcher to subscribers"""

    streamer_name: str
    chat_message: 'stream.ChatMessage'
    subscribers: List['ui.User']


@dataclass
class Notification:
    """Common message to users"""

    users: List['ui.User']
    message: str
