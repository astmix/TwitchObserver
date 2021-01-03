import asyncio
import concurrent.futures
import logging as log
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, List, Awaitable

import feedback as fb

if TYPE_CHECKING:
    import sender


def _ratio_passed(matcher: SequenceMatcher, threshold: float) -> bool:
    return matcher.ratio() >= threshold


class MessageMatcher:
    """
    Class responsible to process message from
    stream sessions with given hook users patterns
    """

    def __init__(self,
                 executor: concurrent.futures.ThreadPoolExecutor,
                 sender: 'sender.MessageSender') -> None:
        self._log = log.getLogger('MessageMatcher')
        self._sender = sender
        self._executor = executor

    def _create_tasks(self, data: fb.StreamFeedback) -> List[Awaitable]:
        loop = asyncio.get_running_loop()

        futures = []
        for sub in data.subscribers:
            matcher = SequenceMatcher(lambda s: s == ' ',
                                      data.chat_message.message,
                                      sub.user.hooks[sub.hook_name])

            futures.append(loop.run_in_executor(self._executor,
                                                _ratio_passed,
                                                matcher,
                                                sub.user.threshold))

        return futures

    async def match(self, data: fb.StreamFeedback) -> None:
        futures = self._create_tasks(data)

        results = await asyncio.gather(*futures)

        passed_subs = [sub.user for sub, passed in
                       zip(data.subscribers, results) if passed]

        if passed_subs:
            match_data = fb.MatcherFeedback(data.streamer_name,
                                            data.chat_message,
                                            passed_subs)
            asyncio.create_task(self._sender.send_matched_data(match_data))
