import time
import datetime
import logging as log
from dataclasses import dataclass
from typing import Dict, Any, Optional

import aiohttp

from errors import ObserverError, StreamNotFoundError


@dataclass
class StreamerDesc:
    """Description of the requested streamer"""

    user_name: str
    started_at: datetime.datetime
    title: str


class TwitchSession:
    """
    Class responsible for sending requests
    to twitch api
    """

    def __init__(self,
                 config: Dict[str, Any],
                 session: aiohttp.ClientSession) -> None:
        self._oauth: Optional[str] = None
        self._client_id = config['twitch_client_id']
        self._client_secret = config['twitch_client_secret']
        self._oauth_request = config['twitch_oauth_url']
        self._expires_in = 0
        self._log = log.getLogger('TwitchSession')
        self._session = session

        api_url = config['twitch_api_url']

        self._streams_request = api_url.format('streams')
        self._clips_request = api_url.format('clips')

    def _get_token(self, data: Dict[str, Any]) -> str:
        try:
            self._expires_in = time.time() + data['expires_in']

            token_type = data['token_type']
            if token_type != 'bearer':
                raise ObserverError(f'Bad token type {token_type}')

            return data['access_token']
        except (KeyError, TypeError) as err:
            self._log.error(err)
            raise ObserverError() from err

    def _parse_stream_info(self, data: Dict[str, Any]) -> StreamerDesc:
        try:
            if info_list := data['data']:
                info = info_list[0]
                user_name = info['user_name']
                title = info['title']
                date_string = info['started_at']
                fmt = '%Y-%m-%dT%H:%M:%SZ'
                started_at = datetime.datetime.strptime(date_string, fmt)
                return StreamerDesc(user_name, started_at, title)
            raise StreamNotFoundError()
        except (KeyError, TypeError) as err:
            self._log.exception(err)
            raise ObserverError() from err

    async def update_token(self) -> None:
        params = {
            'client_id': self._client_id,
            'client_secret': self._client_secret,
            'grant_type': 'client_credentials'
        }

        try:
            async with self._session.post(self._oauth_request,
                                          allow_redirects=False,
                                          raise_for_status=True,
                                          params=params) as resp:
                if resp.status != 200:
                    raise ObserverError(f'Update status: {resp.status}')
                self._oauth = self._get_token(await resp.json())
                self._log.info('Update token OK')
        except aiohttp.ClientError as err:
            self._log.exception(err)
            raise ObserverError() from err

    async def get_stream_description(self, streamer: str) -> StreamerDesc:
        if self._expires_in - time.time() <= 100:
            await self.update_token()

        assert self._oauth is not None

        request_args = {
            'params': {
                'user_login': streamer
            },
            'headers': {
                'Client-Id': self._client_id,
                'Authorization': f'Bearer {self._oauth}'
            }
        }

        try:
            async with self._session.get(self._streams_request,
                                         allow_redirects=False,
                                         raise_for_status=True,
                                         **request_args) as resp:
                if resp.status != 200:
                    raise ObserverError(f'Request status: {resp.status}')
                return self._parse_stream_info(await resp.json())
        except aiohttp.ClientError as err:
            self._log.exception(err)
            raise ObserverError() from err
