import argparse
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
import yaml
from assets.backup import ResticBackup

script_path = os.path.abspath(os.path.dirname(__file__))
log_path = f'{script_path}/logs'
os.makedirs(log_path, exist_ok=True)
log_handler = RotatingFileHandler(f'{log_path}/restic.log', maxBytes=5242880, backupCount=5, encoding='utf-8')
logging.basicConfig(handlers=[log_handler], level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', datefmt='%d/%m/%Y %I:%M:%S %p')
config_location = f'{script_path}/config/config.yml'
logging.info(f'Opening {config_location} as the configuration file.')

try:
    with open(config_location) as config_file:
        config = yaml.safe_load(config_file)
except FileNotFoundError:
    print('Configuration file cannot be opened.')
    logging.error(f'No configuration file at: {config_location}.')
    sys.exit(1)
except yaml.YAMLError as e:
    print(f'Error parsing {config_location}: {e}')
    logging.error(f'Error parsing {config_location}: {e}')
    sys.exit(1)

def load_environment(restic_task):

    '''
    Tasks can be set to enabled = true or enabled = false to skip.
    Once the task is checked and enabled the task keys are returned to be used.
    '''
    task_config = config['servers'].get(restic_task)
    if not task_config:
        return None
    elif task_config.get('enabled') is not True:
        print(f'Skipping {restic_task} as it is disabled in the configuration file.')
        return None
    return task_config

def choice(action, task, snapshot_id, restore_path, single, command):
    '''
    To trigger the actions. Returns True if the action succeeded.
    Restore, init and mount cannot run for all repos, a single repo must be chosen with --single <repo>
    '''
    logging.info(f'Task is set to {action}')
    if action == 'other':
        if not command:
            print('Command is empty.')
            return False
        return task.other(command)
    elif action == 'backup':
        return task.backup()
    elif action == 'forget':
        return task.forget()
    elif action == 'snapshots':
        return task.list_snapshots()
    elif action == 'restore':
        return task.restore(snapshot_id, restore_path)
    elif action == 'mount':
        return task.mount(restore_path)
    elif action == 'init':
        return task.create()
    return False

def main():
    parser = argparse.ArgumentParser(description='Create and manage backups using restic.')
    parser.add_argument('--single', type=str, help='Single repo from config.')
    parser.add_argument('--snapshot_id', type=str, help='Use snapshot ID as argument.')
    parser.add_argument('--restore_path', type=str, help='Set restore path (also the mountpoint for mount).')
    parser.add_argument('--command', type=str, help='Pass other command.')
    parser.add_argument('action', type=str, help='init, backup, restore, snapshots, mount, forget or other.', choices=['init', 'backup', 'forget', 'snapshots', 'restore', 'mount', 'other'])
    args = parser.parse_args()
    single = args.single
    servers = config.get('servers') or {}
    restic_path = config['restic_path']
    ntfy_config = config.get('ntfy')

    if args.action in ('restore', 'mount', 'init') and not single:
        print(f'Cannot {args.action} all repos, use --single.')
        logging.warning(f'Action was set to {args.action} but all repos were selected. Exiting.')
        sys.exit(1)

    if single:
        if single not in servers:
            print('Selection cannot be found in config file.')
            logging.warning(f'Selection {single} cannot be found in config file.')
            sys.exit(1)
        selected = [single]
    else:
        selected = list(servers)

    failed = []
    for restic_task in selected:
        loaded_config = load_environment(restic_task)
        if loaded_config is None:
            continue
        task = ResticBackup(loaded_config, restic_path, script_path, ntfy_config=ntfy_config)
        if not choice(args.action, task, args.snapshot_id, args.restore_path, single, args.command):
            failed.append(restic_task)

    # A non-zero exit code lets the orchestrator client know the run failed.
    if failed:
        logging.error(f'{args.action} failed for: {", ".join(failed)}.')
        sys.exit(1)

if __name__ == '__main__':
    main()
