import argparse
import os
import sys
import logging
import yaml
from assets.backup import ResticBackup

script_path = os.path.abspath(os.path.dirname(__file__))
logging.basicConfig(filename=f'{script_path}/config/restic.log', encoding='utf-8', level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%d/%m/%Y %I:%M:%S %p')
config_location = f'{script_path}/config/config.yml'
logging.info(f'Opening {config_location} as the configuration file.')

try:
    with open(config_location) as config_file:
        config = yaml.safe_load(config_file)
except FileNotFoundError:
    print('Configuration file cannot be opened.')
    logging.debug(f'No configuration file at: {config_location}.')
    exit()

def load_environment(restic_task):

    '''
    Checking if the basic keys exist on the config file, if it doesn't it will exit.
    Tasks can be set to enabled = true or enabled = false to skip.
    Once keys are checked and task is enabled the task keys are returned to be used.
    '''
    if not config['servers'][restic_task]:
        return None
    elif config['servers'][restic_task]['enabled'] is not True:
        print(f'Skipping {restic_task} as it is disabled in the configuration file.')
        return None
    return config['servers'][restic_task]

def choice(action, task, snapshot_id, restore_path, single, command):
    '''
    To trigger the actions.
    Restore, create and mount cannot run for all repos, a single repo must be chosen with --single <repo>
    '''
    logging.info(f'Task is set to {action}')
    if action == 'other':
        if not command:
            print(f'Command is empty.')
            sys.exit()
        task.other(command)
    if action == 'backup':
        options = task.option_parser()
        task.backup(options)
    elif action == 'forget':
        task.forget()
    elif action == 'snapshots':
        task.list_snapshots()
    elif action == 'restore':
        if not single:
            print(f'Cannot {action} all repos, use --single.')
            logging.warning(f'Action was set to {action} but all repos were selected. Exiting.')
            sys.exit()
        task.restore(snapshot_id, restore_path)
    elif action == 'mount':
        if not single:
            print(f'Cannot {action} all repos, use --single.')
            logging.warning(f'Action was set to {action} but all repos were selected. Exiting.')
            sys.exit()
        task.mount(restore_path)
    elif action == 'init':
        if not single:
            print(f'Cannot {action} all repos, use --single.')
            logging.warning(f'Action was set to {action} but all repos were selected. Exiting.')
            sys.exit()
        task.create()

def main():
    parser = argparse.ArgumentParser(description='Create and manage backups using restic.')
    parser.add_argument('--single', type=str, help='Single repo from config.')
    parser.add_argument('--snapshot_id', type=str, help='Use snapshot ID as argument.')
    parser.add_argument('--restore_path', type=str, help='Set restore path.')
    parser.add_argument('--command', type=str, help='Pass other command.')
    parser.add_argument('action', type=str, help='init, backup, restore, snapshots, mount or forget.', choices=['init', 'backup', 'forget', 'snapshots', 'restore', 'mount', 'other'])
    args = parser.parse_args()
    single = args.single
    action = args.action
    snapshot_id = args.snapshot_id
    restore_path = args.restore_path
    command = args.command
    servers = config['servers']
    restic_path = config['restic_path']
    if single in servers:
        loaded_config = load_environment(single)
        if loaded_config is None:
            sys.exit() 
        task = ResticBackup(loaded_config, restic_path, script_path)
        choice(action, task, snapshot_id, restore_path, single, command)
    elif single == '' or single == None:
        for restic_task in servers:
            loaded_config = load_environment(restic_task)
            if loaded_config is None:
                continue
            task = ResticBackup(loaded_config, restic_path, script_path)
            choice(action, task, snapshot_id, restore_path, single, command)
    else:
        print(f'Selection cannot be found in config file.')
        logging.warning(f'Selection cannot be found in config file.')

if __name__ == '__main__':
    main()
