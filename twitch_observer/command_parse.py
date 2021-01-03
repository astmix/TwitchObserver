from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Any

from errors import CommandParseError


class CommandType(Enum):
    """ Parsed command type"""

    START = auto()
    STOP = auto()
    STOP_ALL = auto()
    HOOK = auto()
    ALL_HOOKS = auto()
    THRESHOLD = auto()
    HELP = auto()


@dataclass
class CommandDesc:
    """Parsed command description"""

    command_type: CommandType
    parameters: Dict[str, Any]


def _parse_start_command(data: List[str]) -> Dict[str, Any]:
    if not data:
        raise CommandParseError('Wrong start command arguments')

    values = data[0].split()

    if len(values) > 2:
        raise CommandParseError('Too many start command arguments')
    if len(values) < 2:
        raise CommandParseError('Too few start command arguments')

    params = {
        'streamer': values[0],
        'hook_name': values[1]
    }

    return params


def _parse_stop_command(data: List[str]) -> Dict[str, Any]:
    if not data:
        raise CommandParseError('Wrong stop command arguments')

    values = data[0].split()

    if len(values) != 1:
        raise CommandParseError('Unexpected stop command arguments')

    params = {
        'streamer': values[0]
    }

    return params


def _parse_stopall_command(data: List[str]) -> Dict[str, Any]:
    if data:
        raise CommandParseError('Unexpected stop_all command arguments')

    return dict()


def _parse_hook_command(data: List[str]) -> Dict[str, Any]:
    if not data:
        raise CommandParseError('Wrong hook command arguments')

    name, *words = data[0].split(maxsplit=1)

    if not(name.endswith(':') and len(name) > 1):
        raise CommandParseError('Hook name not found')
    if not words:
        raise CommandParseError('Empty words list')

    params = {
        'hook_name': name[:-1],
        'hook_str': words[0]
    }

    return params


def _parse_hooks_command(data: List[str]) -> Dict[str, Any]:
    if data:
        raise CommandParseError('Unexpected hooks command arguments')

    return dict()


def _parse_threshold_command(data: List[str]) -> Dict[str, Any]:
    if not data:
        raise CommandParseError('Too few threshold command arguments')

    value_str, *rest = data[0].split(maxsplit=1)

    try:
        value = float(value_str)
    except ValueError as err:
        raise CommandParseError('Unexpected threshold value') from err

    if rest:
        raise CommandParseError('Too many threshold command arguments')
    if value < 0.0 or value > 1.0:
        raise CommandParseError('Wrong threshold value (0.0 <= value <= 1.0)')

    params = {
        'threshold': value,
    }

    return params


def _parse_help_command() -> Dict[str, Any]:
    commands = """Support commands:
        /start streamer hook - start tracking streamer with hook
        /stop streamer - stop tracking streamers
        /stop_all - stop tracking everyone
        /hook name: [words]
        /hooks - show all hooks
        /threshold value - set threshold (0.0 - 1.0) default 0.5
        /? - Help message
        """

    params = {
        'commands': commands
    }

    return params


def parse_command(command: str):
    command_name, *data = command.split(maxsplit=1)

    if command_name == '/start':
        return CommandDesc(CommandType.START,
                           _parse_start_command(data))

    if command_name == '/stop':
        return CommandDesc(CommandType.STOP,
                           _parse_stop_command(data))

    if command_name == '/stop_all':
        return CommandDesc(CommandType.STOP_ALL,
                           _parse_stopall_command(data))

    if command_name == '/hook':
        return CommandDesc(CommandType.HOOK,
                           _parse_hook_command(data))

    if command_name == '/hooks':
        return CommandDesc(CommandType.ALL_HOOKS,
                           _parse_hooks_command(data))

    if command_name == '/threshold':
        return CommandDesc(CommandType.THRESHOLD,
                           _parse_threshold_command(data))

    if command_name == '/?':
        return CommandDesc(CommandType.HELP,
                           _parse_help_command())

    raise CommandParseError(f'Unknown command {command_name}')
