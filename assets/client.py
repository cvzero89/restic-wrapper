import requests
import subprocess
import socket
import time
import logging
import os
from misc import setup_logging, import_configuration
from notify import send_notification

logger = logging.getLogger(__name__)

def run_job(server_url, client_id, cmd, job, headers, ntfy_config=None):
    '''
    Ask the server whether <job> is due, run it if so and report the result.
    restic.py exits non-zero when any repo fails, which is what decides success here.
    '''
    check_endpoint, report_endpoint = {
        'backup': ('/register', '/report'),
        'forget': ('/forget', '/forget/report'),
    }[job]
    try:
        logger.info(f'[{client_id}] Checking {job} at {server_url}...')
        check = requests.post(f"{server_url}{check_endpoint}", json={"id": client_id}, headers=headers, timeout=10)
        check.raise_for_status()
        action = check.json().get("action", "ok")
    except Exception as e:
        logger.error(f"[{client_id}] Error checking {job}: {e}")
        return

    if action != job:
        logger.info(f"[{client_id}] No {job} needed.")
        return

    logger.info(f"[{client_id}] Running {job}...")
    try:
        subprocess.run(cmd, check=True)
        success = True
    except (subprocess.CalledProcessError, OSError) as e:
        logger.error(f"[{client_id}] {job.capitalize()} failed: {e}")
        success = False
        send_notification(
            ntfy_config,
            title=f'{job.capitalize()} Failed - {client_id}',
            message=f'{job.capitalize()} command failed on client {client_id}.\n{e}',
            success=False,
        )

    try:
        requests.post(f"{server_url}{report_endpoint}", json={"id": client_id, "success": success}, headers=headers, timeout=10).raise_for_status()
        logger.info(f'[{client_id}] Sent {job} report to server with status: {success}.')
    except Exception as e:
        logger.error(f"[{client_id}] Failed to report {job} result: {e}")


def main():
    script_path=os.path.abspath(os.path.dirname(__file__))
    loaded_config = import_configuration(f'{script_path}/../config/client.yaml')
    setup_logging(loaded_config, script_path)

    server_url = loaded_config['server_url'].rstrip('/')
    python_interp = loaded_config['python_interp']
    restic_cli_path = f'{script_path}/../restic.py'
    restic_cmd = [python_interp, restic_cli_path, "backup"]
    forget_cmd = [python_interp, restic_cli_path, "forget"]
    ntfy_config = loaded_config.get('ntfy')
    auth_token = loaded_config.get('auth_token')
    headers = {'Authorization': f'Bearer {auth_token}'} if auth_token else {}

    check_interval = loaded_config.get('check_interval', 6) * 60 * 60  # hours to seconds
    client_id = loaded_config.get('client_id') or socket.gethostname()
    while True:
        run_job(server_url, client_id, restic_cmd, 'backup', headers, ntfy_config)
        time.sleep(60)
        run_job(server_url, client_id, forget_cmd, 'forget', headers, ntfy_config)
        time.sleep(check_interval)

if __name__ == "__main__":
    main()
