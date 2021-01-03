import asyncio
import logging as log
from typing import TYPE_CHECKING, Any, Generator, Dict
from dataclasses import dataclass

import aiohttp

import command_parse as parse
import stream
import userinfo as ui
import feedback as fb
from errors import StreamNotFoundError, ObserverError, CommandParseError

if TYPE_CHECKING:
    import sender
    import matcher
    import twitch


@dataclass
class StreamContext:
    """Stream session description"""

    session: stream.StreamSession
    task: asyncio.Task


class ActivityObserver:
    """
    Class responsible for receiving commands
    from telegram chats
    """

    def __init__(self,
                 config: Dict[str, Any],
                 session: aiohttp.ClientSession,
                 sender: 'sender.MessageSender',
                 twitch: 'twitch.TwitchSession',
                 matcher: 'matcher.MessageMatcher') -> None:
        self._users: Dict[str, ui.User] = {}
        self._streamers: Dict[str, StreamContext] = {}
        self._cfg = config
        self._sender = sender
        self._twitch = twitch
        self._log = log.getLogger('ActivityObserver')
        self._offset = 0
        self._session = session
        self._matcher = matcher

        api_url = config['telegram_api_url']

        self._poll_request = api_url.format('getUpdates')
        self._edit_markup_request = api_url.format('editMessageReplyMarkup')

    def __await__(self) -> Generator:
        return self._start_poller().__await__()

    async def _process_message(self, data: Dict[str, Any]) -> None:
        try:
            if data['from']['is_bot']:
                self._log.debug('Ignore message from bot')
                return

            user = self._get_user(data['chat'])

            text = data['text']
            if text.startswith('/'):
                await self._process_command(user, text)
        except (KeyError, TypeError) as err:
            self._log.exception(err)

    def _notify(self, user: ui.User, msg: str) -> None:
        data = fb.Notification([user], msg)
        asyncio.create_task(self._sender.send_notification(data))

    def _remove_session(self, session: stream.StreamSession) -> None:
        session.unsubscribe_all()
        del self._streamers[session.name]

    async def _process_start_command(self,
                                     user: ui.User,
                                     *,
                                     streamer: str,
                                     hook_name: str) -> None:
        if streamer in user.streamers:
            self._notify(user, f'Streamer {streamer} already tracked')
            return

        if hook_name not in user.hooks:
            self._notify(user, f'Hook {hook_name} not found')
            return

        try:
            desc = await self._twitch.get_stream_description(streamer)
        except StreamNotFoundError:
            self._notify(user, f'Stream {streamer} not exists or offline')
            return

        if streamer not in self._streamers:
            session = stream.StreamSession(self._cfg, streamer,
                                           self._session, self._sender,
                                           self._matcher, desc.started_at)
            task = asyncio.create_task(self._run_stream(session))
            self._streamers[streamer] = StreamContext(session, task)
        else:
            session = self._streamers[streamer].session

        session.subscribe(user, hook_name)
        user.streamers[streamer] = session

        notify_msg = f"""Now you tracking {desc.user_name}
        started at: {desc.started_at}
        title: {desc.title}
        """

        self._notify(user, notify_msg)

    def _process_stop_command(self, user: ui.User, *, streamer: str) -> None:
        if streamer in user.streamers and streamer in self._streamers:
            context = self._streamers[streamer]
            context.session.unsubscribe(user)

            if not context.session.has_subscribers():
                context.task.cancel()
                del self._streamers[streamer]

            del user.streamers[streamer]
            self._notify(user, f'Stop tracking {streamer}')
        else:
            self._notify(user, f'You do not tracking {streamer}')

    def _process_stopall_command(self, user: ui.User) -> None:
        for name in user.streamers.keys():
            context = self._streamers[name]
            context.session.unsubscribe(user)

            if not context.session.has_subscribers():
                context.task.cancel()
                del self._streamers[name]

        stopped_streamers = ' '.join(user.streamers.keys())
        self._notify(user, f'Stop tracking {stopped_streamers}')
        user.streamers.clear()

    def _process_help_command(self, user: ui.User, *, commands: str) -> None:
        self._notify(user, commands)

    def _process_hook_command(self,
                              user: ui.User,
                              *,
                              hook_name: str,
                              hook_str: str) -> None:
        if hook_name in user.hooks:
            self._notify(user, f'Replace hook {hook_name}: {hook_str}')
        else:
            self._notify(user, f'Set new hook {hook_name}: {hook_str}')

        user.hooks[hook_name] = hook_str

    def _process_hooks_command(self, user: ui.User) -> None:
        if not user.hooks:
            self._notify(user, 'Empty hooks list')
            return

        hooks = []
        for name, hook_str in user.hooks.items():
            hooks.append(f'{name}: {hook_str}')

        result = '\r\n'.join(hooks)
        self._notify(user, result)

    def _process_threshold_command(self,
                                   user: ui.User,
                                   *,
                                   threshold: float) -> None:
        self._notify(user, f'You set new threshold {threshold}')
        user.threshold = threshold

    async def _process_command(self, user: ui.User, command: str) -> None:
        try:
            desc = parse.parse_command(command)
        except CommandParseError as err:
            self._log.debug('%s from %s', err, user.name)
            self._notify(user, str(err))
            return

        if desc.command_type == parse.CommandType.START:
            self._log.info('Handle start command from %s', user.name)
            async with user.start_lock:
                await self._process_start_command(user, **desc.parameters)
        elif desc.command_type == parse.CommandType.STOP:
            self._log.info('Handle stop command from %s', user.name)
            self._process_stop_command(user, **desc.parameters)
        elif desc.command_type == parse.CommandType.STOP_ALL:
            self._log.info('Handle stop all command from %s', user.name)
            self._process_stopall_command(user)
        elif desc.command_type == parse.CommandType.HOOK:
            self._log.info('Handle hook command from %s', user.name)
            self._process_hook_command(user, **desc.parameters)
        elif desc.command_type == parse.CommandType.ALL_HOOKS:
            self._log.info('Handle hooks command from %s', user.name)
            self._process_hooks_command(user)
        elif desc.command_type == parse.CommandType.HELP:
            self._log.info('Handle help command from %s', user.name)
            self._process_help_command(user, **desc.parameters)
        elif desc.command_type == parse.CommandType.THRESHOLD:
            self._log.info('Handle threshold command from %s', user.name)
            self._process_threshold_command(user, **desc.parameters)
        else:
            assert False

    def _get_user(self, chat: Dict[str, Any]) -> ui.User:
        name = chat['username']
        chat_id = chat['id']

        if name not in self._users:
            self._users[name] = ui.User(name, chat_id, dict(), dict())
        return self._users[name]

    def _handle_updates(self, data: Dict[str, Any]) -> None:
        try:
            if data['ok']:
                for res in data['result']:
                    self._offset = res['update_id'] + 1
                    msg = res['message']
                    asyncio.create_task(self._process_message(msg))
            else:
                self._log.error('Data is not ok: %s', data)
        except (KeyError, TypeError) as err:
            self._log.exception(err)

    async def _poll(self) -> None:
        params = {'offset': self._offset}

        async with self._session.get(self._poll_request,
                                     allow_redirects=False,
                                     raise_for_status=True,
                                     params=params) as resp:
            if resp.status == 200:
                self._handle_updates(await resp.json())
            else:
                self._log.warning('Poll status: %d, %s',
                                  resp.status, resp.reason)

    async def _start_poller(self) -> None:
        await self._twitch.update_token()
        await asyncio.gather(self._run_command_polling(),
                             self._run_streams_ping())

    async def _run_command_polling(self) -> None:
        while True:
            try:
                await self._poll()
            except (aiohttp.ClientResponseError,
                    aiohttp.ClientPayloadError) as err:
                self._log.error(err)
            except (aiohttp.ClientConnectionError,
                    aiohttp.InvalidURL) as err:
                self._log.exception(err)
                raise ObserverError() from err

            await asyncio.sleep(0.35)

    async def _run_streams_ping(self) -> None:
        while True:
            await asyncio.sleep(60)

            tasks = [self._twitch.get_stream_description(streamer)
                     for streamer in self._streamers]

            if not tasks:
                continue

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for streamer, desc in zip(self._streamers, results):
                if isinstance(desc, StreamNotFoundError):
                    context = self._streamers[streamer]
                    context.task.cancel()
                    self._remove_session(context.session)
                elif isinstance(desc, Exception):
                    self._log.exception(desc)

    async def _run_stream(self, session: stream.StreamSession) -> None:
        try:
            await session.start_session()
        except ObserverError as err:
            self._log.exception(err)
            self._remove_session(session)
