

class ObserverError(Exception):
    """Runtime exception of twitch observer"""


class StreamNotFoundError(Exception):
    """Requested stream not exists or offline"""


class CommandParseError(Exception):
    """User input parse error"""
