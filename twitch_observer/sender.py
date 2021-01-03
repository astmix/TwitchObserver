import asyncio
import logging as log
import json
from typing import TYPE_CHECKING, Any, Union, Dict, List

import aiohttp

import feedback as fb
from errors import ObserverError

if TYPE_CHECKING:
    import userinfo as ui


Feedback = Union[fb.MatcherFeedback, fb.Notification]


class MessageSender:
    """
    Class responsible for sending messages
    to telegram chats
    """

    def __init__(self,
                 config: Dict[str, Any],
                 session: aiohttp.ClientSession) -> None:
        self._log = log.getLogger('MessageSender')
        self._request = config['telegram_api_url'].format('sendMessage')
        self._session = session

    async def _post(self, params: Dict[str, Any]) -> None:
        while True:
            async with self._session.post(self._request,
                                          allow_redirects=False,
                                          raise_for_status=False,
                                          params=params) as resp:
                if resp.status == 200:
                    return
                if resp.status == 429:
                    self._log.warning('Api limit exceeded')
                    await asyncio.sleep(0.35)
                elif resp.status >= 400:
                    raise ObserverError(f'Post error: {resp.status}')
                else:
                    self._log.warning('Poll status: %d, %s',
                                      resp.status, resp.reason)
                    return

    async def send_matched_data(self, data: fb.MatcherFeedback) -> None:
        inline_keyboard = {
            'inline_keyboard': [[{
                'text': f'Open {data.streamer_name}',
                'url': f'https://www.twitch.tv/{data.streamer_name}'
            }]]
        }

        params: Dict[str, Any] = {
            'disable_notification': 'true',
            'disable_web_page_preview': 'true',
            'reply_markup': json.dumps(inline_keyboard)
        }

        text = f'{data.chat_message.nickname}: {data.chat_message.message}'
        from_start = str(data.chat_message.from_start).split('.')[0]
        params['text'] = f'{data.streamer_name} +{from_start}\r\n\r\n{text}'

        await self._dispatch_data(data.subscribers, params.copy())

    async def send_notification(self, data: fb.Notification) -> None:
        params: Dict[str, Any] = {
            'text': data.message
        }

        await self._dispatch_data(data.users, params.copy())

    async def _dispatch_data(self,
                             users: List['ui.User'],
                             data: Dict[str, Any]) -> None:
        tasks = []
        for user in users:
            data['chat_id'] = user.chat_id
            tasks.append(self._post(data.copy()))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                self._log.exception(result)
