import datetime
import logging
import socket
from python_ntfy import NtfyClient, MessagePriority

logger = logging.getLogger(__name__)

# DD/MM/YY HH:MM
TIME_FORMAT = '%d/%m/%y %H:%M'

def timestamp(when=None):
    return (when or datetime.datetime.now()).strftime(TIME_FORMAT)

def local_hostname():
    '''
    Short name of the machine being backed up, e.g. "laptop" instead of "laptop.local".
    '''
    return socket.gethostname().split('.')[0]

def _build_client(ntfy_config):
    '''
    Build an NtfyClient from the ntfy config dict.
    Auth can be a token string (Bearer) or a list [username, password] (Basic).
    '''
    auth = ntfy_config.get('auth')
    if isinstance(auth, list) and len(auth) == 2:
        auth = tuple(auth)

    return NtfyClient(
        topic=ntfy_config['topic'],
        server=ntfy_config.get('server', 'https://ntfy.sh'),
        auth=auth,
    )

def send_notification(ntfy_config, title, message, success=True):
    '''
    Send a notification via ntfy.
    Skips silently if ntfy is not configured or disabled.
    '''
    if not ntfy_config or not ntfy_config.get('enabled', False):
        return

    try:
        client = _build_client(ntfy_config)
        priority = MessagePriority.DEFAULT if success else MessagePriority.HIGH
        tags = ['white_check_mark'] if success else ['x']

        client.send(
            message=message,
            title=title,
            priority=priority,
            tags=tags,
        )
        logger.info(f'Sent ntfy notification: {title}')
    except Exception as e:
        logger.warning(f'Failed to send ntfy notification: {e}')
