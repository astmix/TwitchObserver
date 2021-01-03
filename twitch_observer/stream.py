import asyncio
import logging as log
import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Dict, Any

import aiohttp

import feedback as fb
from errors import ObserverError

if TYPE_CHECKING:
    import sender
    import matcher
    import userinfo as ui


Websocket = aiohttp.ClientWebSocketResponse


@dataclass
class ChatMessage:
    """Chat message description recieved from twitch stream"""

    nickname: str
    message: str
    from_start: datetime.timedelta


@dataclass
class Subscribe:
    """User subscribe on stream session description """

    user: 'ui.User'
    hook_name: str


class StreamSession:
    """
    Class responsible for receiving messages
    from the chat from the twitch stream
    """

    def __init__(self,
                 config: Dict[str, Any],
                 streamer_name: str,
                 session: aiohttp.ClientSession,
                 sender: 'sender.MessageSender',
                 matcher: 'matcher.MessageMatcher',
                 started_at: datetime.datetime) -> None:
        self._subs: Dict[str, Subscribe] = {}
        self._twitch_irc_url = config['twitch_irc_url']
        self._token = config['twitch_irc_token']
        self._nickname = config['nickname']
        self._max_reconnect_attempts = config['max_stream_reconnects']
        self._log = log.getLogger(f'Stream_{streamer_name}')
        self._session = session
        self._name = streamer_name
        self._sender = sender
        self._matcher = matcher
        self._started_at = started_at

    @property
    def name(self) -> str:
        return self._name

    def subscribe(self, user: 'ui.User', hook_name: str) -> None:
        self._subs[user.name] = Subscribe(user, hook_name)

    def unsubscribe(self, user: 'ui.User') -> None:
        del self._subs[user.name]

    def has_subscribers(self) -> bool:
        return bool(self._subs)

    def unsubscribe_all(self, *, notify: bool = True) -> None:
        if notify:
            self._notify_subs(f'{self._name} stream closed')
        for sub in self._subs.values():
            del sub.user.streamers[self._name]

    async def start_session(self) -> None:
        max_reconnect_attempts = self._max_reconnect_attempts

        while max_reconnect_attempts > 0:
            await self._start_chat_session()
            self._log.warning('Trying to reconnect...')
            max_reconnect_attempts -= 1

        raise ObserverError('Websocket connection error')

    async def _start_chat_session(self) -> None:
        try:
            async with self._session.ws_connect(self._twitch_irc_url) as ws:
                await ws.send_str(f'PASS {self._token}')
                await ws.send_str(f'NICK {self._nickname}')
                await ws.send_str(f'JOIN #{self._name}')
                await self._start(ws)
        except aiohttp.WSServerHandshakeError:
            self._log.warning('Handshake error')

    async def _start(self, ws: Websocket) -> None:
        try:
            await self._recv_chat_messages(ws)
        finally:
            if not ws.closed:
                self._log.info('Leave channel %s', self._name)
                await ws.send_str(f'PART #{self._name}')

    def _parse_msg(self, data: str) -> Optional[ChatMessage]:
        parts = data.split(maxsplit=3)

        if len(parts) == 4 and parts[1] == 'PRIVMSG':
            nickname = parts[0][1:].split('!', maxsplit=1)[0]
            message = parts[3][1:].split('\r\n', maxsplit=1)[0]
            from_start = datetime.datetime.now() - self._started_at
            return ChatMessage(nickname, message, from_start)

        self._log.debug('Not a message: %s', data)
        return None

    def _enqueue_message(self, message: ChatMessage) -> None:
        subs = list(self._subs.values())
        data = fb.StreamFeedback(self._name, message, subs)
        asyncio.create_task(self._matcher.match(data))

    def _notify_subs(self, message: str) -> None:
        subs = [sub.user for sub in self._subs.values()]
        data = fb.Notification(subs, message)
        asyncio.create_task(self._sender.send_notification(data))

    async def _recv_chat_messages(self, ws: Websocket) -> None:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                if msg.data.startswith('PING'):
                    self._log.debug('Send PONG message to %s', self._name)
                    pong_msg = 'PONG :tmi.twitch.tv'
                    asyncio.create_task(ws.send_str(pong_msg))
                elif (res := self._parse_msg(msg.data)) is not None:
                    self._log.debug('Recieve message %s', res.message)
                    self._enqueue_message(res)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                self._log.error('Error on %s websocket', self._name)
                break

        self._log.warning('Websocket closed with code %d', ws.close_code)
