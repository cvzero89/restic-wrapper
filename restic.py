import argparse
import subprocess
import datetime
import json
import os
import sys
import logging

script_path = os.path.abspath(os.path.dirname(__file__))
logging.basicConfig(filename=f'{script_path}/config/restic.log', encoding='utf-8', level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%d/%m/%Y %I:%M:%S %p')
config_location = f'{script_path}/config/.config_restic.json'
config = open(config_location)
logging.info(f'Opening {config_location} as the configuration file.')
try:
    config_file = json.load(config)
    loaded_keys = list(config_file.keys())
except ValueError as error_loading:
    print(f'Error decoding JSON file!\n{error_loading}')
    logging.debug(f'Error decoding JSON file! Please check {config}.')
    exit()

def load_environment(restic_task):

    '''
    Checking if the basic keys exist on the config file, if it doesn't it will exit.
    Tasks can be set to enabled = true or enabled = false to skip.
    Once keys are checked and task is enabled the task keys are returned to be used.
    '''
    try:
        config_file[restic_task][0]['type'], config_file[restic_task][0]['host'], config_file[restic_task][0]['repo_path'], config_file[restic_task][0]['backup_path'], config_file[restic_task][0]['password_file']
        if config_file[restic_task][0]['enabled'] == False:
            print(f'{restic_task} is disabled on the config file. Skipping.')
            return 'disabled'
    except KeyError as error:
        print(f'Could not load key in JSON file for {restic_task}.\nMissing key: {error}')
        logging.debug(f'Could not load key in JSON file for {restic_task}.\nMissing key: {error}')
        return 'KeyError'
    key_values = []
    for key in config_file[restic_task][0].keys():
        key_values.append(config_file[restic_task][0][key])
    return key_values


class ResticBackup:

    '''
    Defining the restic class to backup, list snaphosts, restore, mount and forget.
    Includes a subprocess method that will print output while executing, useful for restores and backups which will take long and will only clear the buffer at the end of the command.
    '''
    def __init__(self, enabled, backup_type, host, repo_path, backup_path, password_file, restic_path, options=None, forget_options=None, exclude=None):
        self.repo_path = repo_path
        self.backup_path = backup_path
        self.options = options
        self.exclude = exclude
        self.backup_type = backup_type
        self.host = host
        self.password_file = password_file
        self.forget_options = forget_options
        self.enabled = enabled
        self.restic = restic_path

    def run_command(self, cmd):
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8')
        '''
        Read and print the output while the process is running.
        Catches the KeyboardInterrupt, needed for the mount closing.
        '''
        try:
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    print(output.strip())
        except KeyboardInterrupt:
            process.terminate()
            process.wait()

        stdout, stderr = process.communicate()
        return stdout, stderr

    def type_selector(self, job, options, forget_list, snapshot_id, restore_path):

        '''
        type_selector is used to modify the restic command based on the type of host used, local, FTP or S3.
        Each task will call it to get a return of the command needed. Some options will differ like forget(daily, weekly, monthly), exclude, etc.
        All commands include --password-file to allow running from cron.
        '''
        if self.backup_type == 'sftp':
            host = f'{self.backup_type}:{self.host}:{self.repo_path}'
        elif self.backup_type == 's3':
            self.s3_env_set()
            host = f'{self.backup_type}:{self.repo_path}'
        else:
            host = f'{self.repo_path}'

        if job == 'backup':
            exclude_file = self.set_exclude()
            cmd = f'{self.restic} -r {host} {options} --exclude-file={exclude_file} {job} {self.backup_path} --password-file {self.password_file}'
        elif job == 'snapshots':
            cmd = f'{self.restic} -r {host} {job} --password-file {self.password_file}'
        elif job == 'restore':
            cmd = f'{self.restic} -r {host} {job} {snapshot_id} --target {restore_path} --password-file {self.password_file}'
        elif job == 'forget':
            cmd = f'{self.restic} -r {host} {job} --keep-daily {forget_list[0]} --keep-weekly {forget_list[1]} --keep-monthly {forget_list[2]} --password-file {self.password_file}'
        elif job == 'init':
            cmd = f'{self.restic} -r {host} {job} --password-file {self.password_file}' 
        elif job == 'mount':
            cmd = f'{self.restic} -r {host} {job} {restore_path} --password-file {self.password_file}'
        else:
            print(f'Task is not defined.')
            logging.warning(f'Task is not defined. Exiting.')
            sys.exit()
        return cmd

    def create(self, options=None, forget_list=None, snapshot_id=None, restore_path=None):
        job = 'init'
        cmd = self.type_selector(job, options, forget_list, snapshot_id, restore_path)
        stdout, stderr = self.run_command(cmd)
        if stderr:
            print(f'Error initializing repository: {stderr}')
            logging.debug(f'Error initializing repository: {stderr}')
            return False
        print(f'{stdout}\nSuccessfully created repo for {self.repo_path} on {self.backup_type}.')
        logging.info(f'Successfully created repo for {self.repo_path} on {self.backup_type}.')


    def backup(self, options, forget_list=None, snapshot_id=None, restore_path=None):
        '''
        Backup options can be set on the config file.
        '''
        job = 'backup'
        now = datetime.datetime.now()
        cmd = self.type_selector(job, options, forget_list, snapshot_id, restore_path) 
        stdout, stderr = self.run_command(cmd)
        if stderr:
           print(f'Error creating backup: {stderr}')
           logging.debug(f'Error creting backup: {stderr}')
           return False
        print(f'{stdout}\nSuccessfully created backup of {self.backup_path} at {now} on {self.backup_type}.')
        logging.info(f'Successfully created backup of {self.backup_path} at {now} on {self.backup_type}.')
    
    def forget(self, forget_list, options=None, snapshot_id=None, restore_path=None):
        '''
        Forget parameters can be set on the config file.
        '''
        job = 'forget'
        now = datetime.datetime.now()
        cmd = self.type_selector(job, options, forget_list, snapshot_id, restore_path)
        stdout, stderr = self.run_command(cmd)
        if stderr:
            print(f'Error forgetting old snapshots: {stderr}')
            logging.debug(f'Error forgetting old snapshots from {self.backup_type}.')
            return False
        print(f'{stdout}\nSuccessfully forgot backup for {self.repo_path} at {now} on {self.backup_type}.')
        logging.info(f'Successfully forgot backup for {self.repo_path} at {now} on {self.backup_type}.')

    def list_snapshots(self, options=None, forget_list=None, snapshot_id=None, restore_path=None):
        job = 'snapshots'
        cmd = self.type_selector(job, options, forget_list, snapshot_id, restore_path)
        print(f'Listing snapshots from {self.backup_type}:')
        stdout, stderr = self.run_command(cmd)
        if stderr:
           print(f'Error listing snapshots: {stderr}')
           logging.debug(f'Error listing snapshots: {stderr}')
           return False
        logging.info(f'Listed snapshots from: {self.backup_type}.')

    def restore(self, snapshot_id, restore_path, options=None, forget_list=None):
        if not snapshot_id or not restore_path:
            logging.warning(f'snapshot ID or restore path missing.')
            print(f'snapshot ID or restore path missing.')
            sys.exit() 
        job = 'restore'
        cmd = self.type_selector(job, options, forget_list, snapshot_id, restore_path)
        stdout, stderr = self.run_command(cmd)
        if stderr:
           print(f'Error restoring snapshot: {stderr}')
           logging.debug(f'Error restoring snapshot: {snapshot_id}.')
           return False
        print(f'Restored snapshot {snapshot_id} from: {self.backup_type} to {restore_path}\n{stdout}')
        logging.info(f'Restored snapshot {snapshot_id} from: {self.backup_type} to {restore_path}')

    def mount(self, restore_path, snapshot_id=None, options=None, forget_list=None):
        '''
        This is to mount the repo to a FUSE mountpoint and browse the files. Useful when there are only a handful of files to restore.
        It assumes FUSE is installed.
        '''

        if not restore_path:
            logging.warning(f'Restore path missing.')
            print(f'Restore path missing.')
            sys.exit() 
        job = 'mount'
        unmount_command = f'umount {restore_path}'
        run_umount = subprocess.Popen(unmount_command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, encoding='utf-8')
        cmd = self.type_selector(job, options, forget_list, snapshot_id, restore_path)
        stdout, stderr = self.run_command(cmd)
        if stderr:
           print(f'Error mounting snapshot: {stderr}')
           logging.debug(f'Error mounting snapshot from: {self.backup_type}.')
           return False
        print(f'Mounted snapshots from: {self.backup_type} to {restore_path}')
        logging.info(f'Mounted snapshots from: {self.backup_type} to {restore_path}')


    def option_parser(self):
        options_dict = self.options
        options = []
        if options_dict:
            if options_dict['no-scan'] == True:
                options.append('--no-scan')
            if options_dict['read-concurrency'] == True:
                options.append('--read-concurrency')
            if options_dict['compression'] == 'auto':
                options.append('--compression=auto')
            if options_dict['compression'] == 'max':
                options.append('--compression=max')
        return ' '.join(options)

    def forget_parser(self):
        forget_dict = self.forget_options
        forget_list = []
        forget_list.extend([str(forget_dict['daily']), str(forget_dict['weekly']), str(forget_dict['monthly'])])
        return forget_list

    def s3_env_set(self):
        '''
        Setting the enviromental variables to connect to S3.
        File location can be changed on .config_restic.json → options>.env-file.
        '''
        os.unsetenv('AWS_ACCESS_KEY_ID')
        os.unsetenv('AWS_SECRET_ACCESS_KEY')
        os.unsetenv('AWS_SECRET_ACCESS_KEY')
        s3_file = self.options['.env-file']
        if self.backup_type == 's3':
            from dotenv import load_dotenv
            load_dotenv(f'{s3_file}')
            os.getenv('AWS_ACCESS_KEY_ID')
            os.getenv('AWS_SECRET_ACCESS_KEY')
            os.getenv('AWS_DEFAULT_REGION')

    def set_exclude(self):
        '''
        The exclude file is created on each run based on the exclude param on the config file.
        Words needs to be separated by comma, no space. If nothing is provided then an empty file is created.
        '''
        exclude_file = f'{script_path}/config/excludes.txt'
        logging.info(f'Excluding terms: {self.exclude}. Creating exclude.txt for {self.backup_type}.')
        with open(exclude_file, 'w') as my_file: 
            for item in self.exclude.split(','):
                my_file.write(f'{item}\n')
        return exclude_file




def choice(action, task, snapshot_id, restore_path, single):
    '''
    To trigger the actions.
    Restore, create and mount cannot run for all repos, a single repo must be chosen with --single <repo>
    '''


    logging.info(f'Task is set to {action}')
    if action == 'backup':
        options = task.option_parser()
        task.backup(options)
    elif action == 'forget':
        forget_list = task.forget_parser()
        task.forget(forget_list)
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
    else:
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
    parser.add_argument('action', type=str, help='init, backup, restore, snapshots, mount or forget.', choices=['init', 'backup', 'forget', 'snapshots', 'restore', 'mount'])
    args = parser.parse_args()
    single = args.single
    action = args.action
    snapshot_id = args.snapshot_id
    restore_path = args.restore_path
    if single in loaded_keys:
        loaded_config = load_environment(single)
        if loaded_config == 'KeyError':
            sys.exit()
        if loaded_config == 'disabled':
            sys.exit() 
        task = ResticBackup(*loaded_config)
        choice(action, task, snapshot_id, restore_path, single)
    elif single == '' or single == None:
        for restic_task in loaded_keys:
            loaded_config = load_environment(restic_task)
            if loaded_config == 'KeyError':
                continue
            if loaded_config == 'disabled':
                continue 
            task = ResticBackup(*loaded_config)
            choice(action, task, snapshot_id, restore_path, single)
    else:
        print(f'Selection cannot be found in JSON file. Running all tasks.')
        logging.warning(f'Selection cannot be found in JSON file. Running all tasks.')

if __name__ == '__main__':
    main()

