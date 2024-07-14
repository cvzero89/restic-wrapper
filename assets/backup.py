import subprocess
import logging
import sys
import datetime
import os
from dotenv import load_dotenv

class ResticBackup:

    '''
    Defining the restic class to backup, list snaphosts, restore, mount and forget.
    Includes a subprocess method that will print output while executing, useful for restores and backups which will take long and will only clear the buffer at the end of the command.
    '''
    def __init__(self, loaded_config, restic_path, script_path, options=None, forget_options=None, exclude=None):
        self.repo_path = loaded_config['repo_path']
        self.backup_path = loaded_config['backup_path']
        self.options = loaded_config['options']
        self.exclude = loaded_config['exclude']
        self.backup_type = loaded_config['type']
        if self.backup_type != 's3':
            self.host = loaded_config['host']
        self.password_file = loaded_config['password_file']
        self.forget_options = loaded_config['forget_options']
        self.enabled = loaded_config['enabled']
        self.script_path = script_path
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
        logging.debug(f'Ran command {cmd}.')
        return stdout, stderr

    def type_selector(self, job, options, snapshot_id, restore_path):

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
            cmd = f'{self.restic} -r {host} {job} --keep-daily {self.forget_options["daily"]} --keep-weekly {self.forget_options["weekly"]} --keep-monthly {self.forget_options["monthly"]} --password-file {self.password_file}'
        elif job == 'init':
            cmd = f'{self.restic} -r {host} {job} --password-file {self.password_file}' 
        elif job == 'mount':
            cmd = f'{self.restic} -r {host} {job} {restore_path} --password-file {self.password_file}'
        elif job[0] == 'other':
            cmd = f'{self.restic} -r {host} {job[1]} --password-file {self.password_file}'
        else:
            print(f'Task is not defined.')
            logging.warning(f'Task is not defined. Exiting.')
            sys.exit()
        return cmd

    def create(self, options=None, snapshot_id=None, restore_path=None):
        job = 'init'
        cmd = self.type_selector(job, options, snapshot_id, restore_path)
        stdout, stderr = self.run_command(cmd)
        if stderr:
            print(f'Error initializing repository: {stderr}')
            logging.debug(f'Error initializing repository: {stderr}')
            return False
        print(f'{stdout}\nSuccessfully created repo for {self.repo_path} on {self.backup_type}.')
        logging.info(f'Successfully created repo for {self.repo_path} on {self.backup_type}.')


    def backup(self, options, snapshot_id=None, restore_path=None):
        '''
        Backup options can be set on the config file.
        '''
        job = 'backup'
        now = datetime.datetime.now()
        cmd = self.type_selector(job, options, snapshot_id, restore_path) 
        stdout, stderr = self.run_command(cmd)
        if stderr:
           print(f'Error creating backup: {stderr}')
           logging.debug(f'Error creting backup: {stderr}')
           return False
        print(f'{stdout}\nSuccessfully created backup of {self.backup_path} at {now} on {self.backup_type}.')
        logging.info(f'Successfully created backup of {self.backup_path} at {now} on {self.backup_type}.')
    
    def forget(self, options=None, snapshot_id=None, restore_path=None):
        '''
        Forget parameters can be set on the config file.
        '''
        job = 'forget'
        now = datetime.datetime.now()
        cmd = self.type_selector(job, options, snapshot_id, restore_path)
        stdout, stderr = self.run_command(cmd)
        if stderr:
            print(f'Error forgetting old snapshots: {stderr}')
            logging.debug(f'Error forgetting old snapshots from {self.backup_type}.')
            return False
        print(f'{stdout}\nSuccessfully forgot backup for {self.repo_path} at {now} on {self.backup_type}.')
        logging.info(f'Successfully forgot backup for {self.repo_path} at {now} on {self.backup_type}.')

    def list_snapshots(self, options=None, snapshot_id=None, restore_path=None):
        job = 'snapshots'
        cmd = self.type_selector(job, options, snapshot_id, restore_path)
        print(f'Listing snapshots from {self.backup_type}:{self.repo_path}.')
        stdout, stderr = self.run_command(cmd)
        if stderr:
           print(f'Error listing snapshots: {stderr}')
           logging.debug(f'Error listing snapshots: {stderr}')
           return False
        logging.info(f'Listed snapshots from: {self.backup_type}:{self.repo_path}.')

    def restore(self, snapshot_id, restore_path, options=None):
        if not snapshot_id or not restore_path:
            logging.warning(f'snapshot ID or restore path missing.')
            print(f'snapshot ID or restore path missing.')
            sys.exit() 
        job = 'restore'
        cmd = self.type_selector(job, options, snapshot_id, restore_path)
        stdout, stderr = self.run_command(cmd)
        if stderr:
           print(f'Error restoring snapshot: {stderr}')
           logging.debug(f'Error restoring snapshot: {snapshot_id}.')
           return False
        print(f'Restored snapshot {snapshot_id} from: {self.backup_type} to {restore_path}\n{stdout}')
        logging.info(f'Restored snapshot {snapshot_id} from: {self.backup_type} to {restore_path}')

    def mount(self, restore_path, snapshot_id=None, options=None):
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
        cmd = self.type_selector(job, options, snapshot_id, restore_path)
        stdout, stderr = self.run_command(cmd)
        if stderr:
           print(f'Error mounting snapshot: {stderr}')
           logging.debug(f'Error mounting snapshot from: {self.backup_type}.')
           return False
        print(f'Mounted snapshots from: {self.backup_type} to {restore_path}')
        logging.info(f'Mounted snapshots from: {self.backup_type} to {restore_path}')

    def other(self, command, options=None, snapshot_id=None, restore_path=None):
        job = ['other', command]
        cmd = self.type_selector(job, options, snapshot_id, restore_path)
        stdout, stderr = self.run_command(cmd)
        if stderr:
            print(f'Ran {command} at  {stderr}')
            logging.debug(f'Ran {command} at {self.backup_type}:{self.repo_path}.')
            return False
        print(f'Ran {command} at {self.backup_type}:{self.repo_path}. {stdout}')
        logging.info(f'Ran {command} at {self.backup_type}:{self.repo_path}.')


    def option_parser(self):
        options_dict = self.options
        options = []
        if options_dict:
            if options_dict['no-scan'] == True:
                options.append('--no-scan')
            if options_dict['read-concurrency'] == True:
                options.append('--read-concurrency')
            if options_dict['compression']:
                compression = f"--compression={options_dict['compression']}"
                options.append(compression)
            try:
                if options_dict['tags']:
                    for tag in options_dict['tags'].split(','):
                        tagger = f'--tag {tag}'
                        options.append(tagger)
            except KeyError:
                ...
        return ' '.join(options)


    def s3_env_set(self):
        '''
        Setting the enviromental variables to connect to S3.
        File location can be changed on .config_restic.json → options>.env-file.
        '''
#        os.unsetenv('AWS_ACCESS_KEY_ID')
#        os.unsetenv('AWS_SECRET_ACCESS_KEY')
#        os.unsetenv('AWS_SECRET_ACCESS_KEY')
        s3_file = self.options['.env-file']
        if self.backup_type == 's3':
            load_dotenv(f'{s3_file}')
            os.getenv('AWS_ACCESS_KEY_ID')
            os.getenv('AWS_SECRET_ACCESS_KEY')
            os.getenv('AWS_DEFAULT_REGION')

    def set_exclude(self):
        '''
        The exclude file is created on each run based on the exclude param on the config file.
        Words needs to be separated by comma, no space. If nothing is provided then an empty file is created.
        '''
        exclude_file = f'{self.script_path}/config/excludes.txt'
        logging.info(f'Excluding terms: {self.exclude}. Creating exclude.txt for {self.backup_type}.')
        with open(exclude_file, 'w') as my_file:
            if self.exclude is not None: 
                for item in self.exclude.split(','):
                    my_file.write(f'{item}\n')
            else:
                with open(exclude_file, 'w'):
                    pass
        return exclude_file
