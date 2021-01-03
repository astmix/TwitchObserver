import asyncio
import json
import logging as log
import functools
import signal
import concurrent.futures
from typing import Any, Dict

import aiohttp

from errors import ObserverError
from observer import ActivityObserver
from sender import MessageSender
from twitch import TwitchSession
from matcher import MessageMatcher


log.basicConfig(
    level=log.INFO,
    format='%(asctime)s,%(msecs)d %(levelname)s %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)


Executor = concurrent.futures.ThreadPoolExecutor


async def _run_session(config: Dict[str, Any], executor: Executor) -> None:
    async with aiohttp.ClientSession() as session:
        sender = MessageSender(config, session)
        matcher = MessageMatcher(executor, sender)
        twitch = TwitchSession(config, session)
        poller = ActivityObserver(config, session, sender, twitch, matcher)

        await poller


async def _run(executor: Executor) -> None:
    try:
        with open('config.json') as cfg_file:
            config = json.load(cfg_file)
    except FileNotFoundError:
        log.error('Config file not found')
    except json.JSONDecodeError as err:
        log.error('Json decode error: %s', err)
    else:
        try:
            await _run_session(config, executor)
        except ObserverError as err:
            log.exception(err)
            raise


async def _shutdown(executor, loop, sig=None):
    if sig is not None:
        log.warning("Received exit signal %s", sig.name)

    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    for task in tasks:
        task.cancel()

    log.warning('Cancelling %d tasks', len(tasks))
    await asyncio.gather(*tasks, return_exceptions=True)

    log.warning("Shutting down executor")
    executor.shutdown(wait=False)

    loop.stop()


def _handle_exception(executor, loop, context):
    msg = context.get('exception', context['message'])
    log.error('Caught exception: %s', msg)
    log.info('Shutting down...')
    asyncio.create_task(_shutdown(executor, loop))


def main():
    executor = concurrent.futures.ThreadPoolExecutor()
    loop = asyncio.get_event_loop()

    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        loop.add_signal_handler(
            s, lambda s=s: asyncio.create_task(_shutdown(executor, loop, s)))

    handle_exc_func = functools.partial(_handle_exception, executor)
    loop.set_exception_handler(handle_exc_func)

    try:
        loop.create_task(_run(executor))
        loop.run_forever()
    finally:
        loop.close()
        log.info('Successfully shutdown')


if __name__ == '__main__':
    main()
