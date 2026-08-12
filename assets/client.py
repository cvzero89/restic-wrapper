import requests
import subprocess
import socket
import time
import logging
import os
from misc import setup_logging, import_configuration
from notify import send_notification

logger = logging.getLogger(__name__)

def run_once(server_url, client_id, restic_cmd, ntfy_config=None):
    try:
        logger.info(f'Registering {client_id} at {server_url}...')
        check = requests.post(f"{server_url}/register", json={"id": client_id}, timeout=10)
        check.raise_for_status()
        action = check.json().get("action", "ok")
    except Exception as e:
        logger.info(f"[{client_id}] Error registering: {e}")
        return

    if action == "backup":
        logger.info(f"[{client_id}] Running backup...")
        try:
            subprocess.run(restic_cmd, check=True)
            success = True
        except subprocess.CalledProcessError as e:
            logger.info(f"[{client_id}] Backup failed: {e}")
            success = False
            send_notification(
                ntfy_config,
                title=f'Backup Failed - {client_id}',
                message=f'Backup command failed on client {client_id}.\n{e}',
                success=False,
            )

        try:
            requests.post(f"{server_url}/report", json={"id": client_id, "success": success}, timeout=10)
            logger.info(f'Sent report to server with status: {success}.')
        except Exception as e:
            logger.info(f"[{client_id}] Failed to report result: {e}")
    else:
        print(f"[{client_id}] No backup needed.")


def run_forget(server_url, client_id, forget_cmd, ntfy_config=None):
    logger.info(f'Checking forget for {client_id}...')
    try:
        check = requests.post(f"{server_url}/forget", json={"id": client_id}, timeout=10)
        check.raise_for_status()
        action = check.json().get("action", "ok")
    except Exception as e:
        logger.info(f"[{client_id}] Error checking forget: {e}")
        return

    if action == "forget":
        logger.info(f"[{client_id}] Running restic forget...")
        try:
            subprocess.run(forget_cmd, check=True)
            success = True
        except subprocess.CalledProcessError as e:
            logger.info(f"[{client_id}] Forget failed: {e}")
            success = False
            send_notification(
                ntfy_config,
                title=f'Forget Failed - {client_id}',
                message=f'Forget command failed on client {client_id}.\n{e}',
                success=False,
            )

        try:
            requests.post(f"{server_url}/forget/report", json={"id": client_id, "success": success}, timeout=10)
            logger.info(f'Sent report to server with status: {success}.')
        except Exception as e:
            logger.info(f"[{client_id}] Failed to report forget result: {e}")


def main():
    script_path=os.path.abspath(os.path.dirname(__file__))
    loaded_config = import_configuration(f'{script_path}/../config/client.yaml')
    setup_logging(loaded_config, script_path)


    server_url = loaded_config['server_url']
    python_interp = loaded_config['python_interp']
    restic_cli_path = f'{script_path}/../restic.py'
    restic_cmd = [python_interp, restic_cli_path, "backup"]
    forget_cmd = [python_interp, restic_cli_path, "forget"]
    ntfy_config = loaded_config.get('ntfy')

    check_interval = loaded_config['check_interval'] * 60 * 60  # 6 hours in seconds
    client_id = loaded_config['client_id'] if loaded_config.get('client_id') else socket.gethostname()
    while True:
        run_once(server_url, client_id, restic_cmd, ntfy_config)
        time.sleep(60)
        run_forget(server_url, client_id, forget_cmd, ntfy_config)
        time.sleep(check_interval)

if __name__ == "__main__":
    main()
