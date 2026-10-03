import subprocess
import logging
import os
import shlex
import json
from dotenv import dotenv_values
from assets.notify import send_notification, timestamp, local_hostname

# restic exit code when a backup snapshot was created but some files could not be read.
RESTIC_INCOMPLETE_SNAPSHOT = 3

class ResticBackup:

    '''
    Defining the restic class to backup, list snaphosts, restore, mount and forget.
    Includes a subprocess method that will print output while executing, useful for restores and backups which will take long and will only clear the buffer at the end of the command.
    Every action returns True on success and False on failure so the caller can set the exit code.
    '''
    def __init__(self, loaded_config, restic_path, script_path, ntfy_config=None):
        self.repo_path = loaded_config['repo_path']
        self.backup_path = loaded_config['backup_path']
        self.options = loaded_config.get('options') or {}
        self.exclude = loaded_config.get('exclude')
        self.backup_type = loaded_config['type']
        self.host = loaded_config.get('host')
        self.password_file = loaded_config['password_file']
        self.forget_options = loaded_config.get('forget_options') or {}
        self.script_path = script_path
        self.restic = restic_path
        self.ntfy_config = ntfy_config

    def run_command(self, cmd):
        '''
        Read and print the output while the process is running.
        stderr is merged into stdout so a chatty stream can never fill its pipe and block restic.
        Catches the KeyboardInterrupt, needed for the mount closing.
        '''
        logging.debug(f'Running command {shlex.join(cmd)}.')
        output = []
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', env=self.build_env()) as process:
            try:
                for line in process.stdout:
                    # --json emits a progress line several times per second, too noisy to print or keep.
                    if json_message(line).get('message_type') == 'status':
                        continue
                    print(line.rstrip())
                    output.append(line)
            except KeyboardInterrupt:
                process.terminate()
        return process.returncode, ''.join(output)

    def repo(self):
        if self.backup_type == 'sftp':
            return f'sftp:{self.host}:{self.repo_path}'
        elif self.backup_type == 's3':
            return f's3:{self.repo_path}'
        return self.repo_path

    def base_command(self, job):
        '''
        All commands include --password-file to allow running from cron.
        '''
        return [self.restic, '-r', self.repo(), '--password-file', self.password_file, *job]

    def build_env(self):
        '''
        S3 credentials are read from the repo's .env-file into the subprocess environment only,
        so repos with different credentials never leak into each other.
        '''
        env = os.environ.copy()
        if self.backup_type == 's3':
            s3_file = self.options.get('.env-file')
            if s3_file:
                env.update({key: value for key, value in dotenv_values(s3_file).items() if value is not None})
        return env

    def unlock(self):
        '''
        Removes only stale locks (left by a crashed or killed restic), never locks of a running process.
        '''
        returncode, output = self.run_command(self.base_command(['unlock']))
        if returncode != 0:
            logging.warning(f'Could not remove stale locks on {self.backup_type}:{self.repo_path} (exit {returncode}): {output[-2000:]}')

    def notify(self, title, message, success):
        '''
        Every notification title names the machine that was backed up.
        '''
        send_notification(self.ntfy_config, title=f'{title} - {local_hostname()}', message=message, success=success)

    def create(self):
        returncode, output = self.run_command(self.base_command(['init']))
        if returncode != 0:
            print(f'Error initializing repository: {output[-2000:]}')
            logging.error(f'Error initializing repository {self.repo_path} on {self.backup_type} (exit {returncode}): {output[-2000:]}')
            return False
        print(f'Successfully created repo for {self.repo_path} on {self.backup_type}.')
        logging.info(f'Successfully created repo for {self.repo_path} on {self.backup_type}.')
        return True

    def backup(self):
        '''
        Backup options can be set on the config file.
        Exit code 3 means the snapshot was created but some files were unreadable: it counts as a success with a warning.
        '''
        when = timestamp()
        self.unlock()
        cmd = self.base_command(['backup', '--json', *self.option_parser(), *self.exclude_args(), self.backup_path])
        returncode, output = self.run_command(cmd)
        summary = backup_summary(output)
        if returncode == RESTIC_INCOMPLETE_SNAPSHOT:
            logging.warning(f'Backup of {self.backup_path} on {self.backup_type} completed with unreadable files: {output[-2000:]}')
            self.notify(
                'Backup Completed With Warnings',
                f'Backed up {self.backup_path} to {self.repo()} at {when}, but some files could not be read.\n{summary}\n{readable_output(output)}',
                success=False,
            )
            return True
        if returncode != 0:
            print(f'Error creating backup (exit {returncode}).')
            logging.error(f'Error creating backup of {self.backup_path} on {self.backup_type} (exit {returncode}): {output[-2000:]}')
            self.notify(
                'Backup Failed',
                f'Backup of {self.backup_path} to {self.repo()} failed at {when}.\n{readable_output(output)}',
                success=False,
            )
            return False
        print(f'Successfully backed up {self.backup_path} to {self.repo()}. {summary}')
        logging.info(f'Successfully backed up {self.backup_path} to {self.repo()}. {summary}')
        self.notify(
            'Backup Successful',
            f'Backed up {self.backup_path} to {self.repo()} at {when}.\n{summary}',
            success=True,
        )
        return True

    def forget(self):
        '''
        Forget parameters can be set on the config file. --prune removes the unreferenced data so the repo actually shrinks.
        '''
        when = timestamp()
        self.unlock()
        cmd = self.base_command([
            'forget', '--prune',
            '--keep-daily', str(self.forget_options.get('daily', 7)),
            '--keep-weekly', str(self.forget_options.get('weekly', 4)),
            '--keep-monthly', str(self.forget_options.get('monthly', 6)),
        ])
        returncode, output = self.run_command(cmd)
        if returncode != 0:
            print(f'Error forgetting old snapshots (exit {returncode}).')
            logging.error(f'Error forgetting old snapshots for {self.repo_path} on {self.backup_type} (exit {returncode}): {output[-2000:]}')
            self.notify(
                'Forget Failed',
                f'Forgetting old snapshots of {self.backup_path} in {self.repo()} failed at {when}.\n{readable_output(output)}',
                success=False,
            )
            return False
        print(f'Successfully forgot old snapshots in {self.repo()}.')
        logging.info(f'Successfully forgot old snapshots in {self.repo()}.')
        self.notify(
            'Forget Successful',
            f'Removed old snapshots of {self.backup_path} from {self.repo()} at {when}.',
            success=True,
        )
        return True

    def list_snapshots(self):
        print(f'Listing snapshots from {self.backup_type}:{self.repo_path}.')
        returncode, output = self.run_command(self.base_command(['snapshots']))
        if returncode != 0:
            logging.error(f'Error listing snapshots from {self.backup_type}:{self.repo_path} (exit {returncode}): {output[-2000:]}')
            return False
        logging.info(f'Listed snapshots from: {self.backup_type}:{self.repo_path}.')
        return True

    def check(self):
        '''
        Verifies the repository structure. Set check_read_data_subset (e.g. 5%) in options to also read back part of the data.
        '''
        when = timestamp()
        subset = self.options.get('check_read_data_subset')
        cmd = self.base_command(['check', *(['--read-data-subset', str(subset)] if subset else [])])
        returncode, output = self.run_command(cmd)
        if returncode != 0:
            logging.error(f'Repository check failed for {self.backup_type}:{self.repo_path} (exit {returncode}): {output[-2000:]}')
            self.notify(
                'Check Failed',
                f'Check of {self.repo()} failed at {when}.\n{readable_output(output)}',
                success=False,
            )
            return False
        logging.info(f'Repository check passed for {self.backup_type}:{self.repo_path}.')
        return True

    def restore(self, snapshot_id, restore_path):
        if not snapshot_id or not restore_path:
            logging.warning('snapshot ID or restore path missing.')
            print('snapshot ID or restore path missing.')
            return False
        returncode, output = self.run_command(self.base_command(['restore', snapshot_id, '--target', restore_path]))
        if returncode != 0:
            logging.error(f'Error restoring snapshot {snapshot_id} (exit {returncode}): {output[-2000:]}')
            return False
        print(f'Restored snapshot {snapshot_id} from: {self.backup_type} to {restore_path}')
        logging.info(f'Restored snapshot {snapshot_id} from: {self.backup_type} to {restore_path}')
        return True

    def mount(self, restore_path):
        '''
        This is to mount the repo to a FUSE mountpoint and browse the files. Useful when there are only a handful of files to restore.
        It assumes FUSE is installed.
        '''
        if not restore_path:
            logging.warning('Restore path missing.')
            print('Restore path missing.')
            return False
        # Clear a leftover mount from a previous run; failure just means nothing was mounted.
        subprocess.run(['umount', restore_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f'Mounting snapshots from: {self.backup_type} to {restore_path}. Press Ctrl+C to unmount.')
        returncode, output = self.run_command(self.base_command(['mount', restore_path]))
        # Ctrl+C ends the mount: restic exits with 130 or is killed by a signal (negative code), both are normal.
        if returncode > 0 and returncode != 130:
            logging.error(f'Error mounting snapshots from {self.backup_type} (exit {returncode}): {output[-2000:]}')
            return False
        logging.info(f'Mounted snapshots from: {self.backup_type} to {restore_path}')
        return True

    def other(self, command):
        returncode, output = self.run_command(self.base_command(shlex.split(command)))
        if returncode != 0:
            logging.error(f'Running {command} at {self.backup_type}:{self.repo_path} failed (exit {returncode}): {output[-2000:]}')
            return False
        logging.info(f'Ran {command} at {self.backup_type}:{self.repo_path}.')
        return True

    def option_parser(self):
        options = []
        if self.options.get('no-scan') is True:
            options.append('--no-scan')
        read_concurrency = self.options.get('read-concurrency')
        if isinstance(read_concurrency, int) and not isinstance(read_concurrency, bool) and read_concurrency > 0:
            options += ['--read-concurrency', str(read_concurrency)]
        if self.options.get('compression'):
            options.append(f"--compression={self.options['compression']}")
        for tag in split_list(self.options.get('tags')):
            options += ['--tag', tag]
        return options

    def exclude_args(self):
        '''
        Excludes come from the exclude param on the config file, either a YAML list or a comma separated string.
        '''
        excludes = split_list(self.exclude)
        logging.info(f'Excluding terms: {excludes} for {self.backup_type}:{self.repo_path}.')
        return [arg for item in excludes for arg in ('--exclude', item)]

def split_list(value):
    if not value:
        return []
    if isinstance(value, str):
        value = value.split(',')
    return [str(item).strip() for item in value if str(item).strip()]

def json_message(line):
    try:
        message = json.loads(line)
    except ValueError:
        return {}
    return message if isinstance(message, dict) else {}

def readable_output(output, limit=1000):
    '''
    The tail of restic's output for a notification, with --json error lines turned back into plain messages.
    '''
    lines = []
    for line in output.splitlines():
        message = json_message(line)
        if not message:
            lines.append(line)
        elif message.get('message_type') == 'error':
            lines.append((message.get('error') or {}).get('message', line))
        elif message.get('message_type') == 'exit_error':
            lines.append(message.get('message', line))
    return '\n'.join(lines).strip()[-limit:]

def human_bytes(size):
    for unit in ('B', 'KiB', 'MiB', 'GiB'):
        if size < 1024:
            return f'{size:.1f} {unit}' if unit != 'B' else f'{size} B'
        size /= 1024
    return f'{size:.1f} TiB'

def backup_summary(output):
    '''
    Builds a one line summary from the summary message of restic backup --json. Empty if there is none.
    '''
    for line in reversed(output.splitlines()):
        message = json_message(line)
        if message.get('message_type') == 'summary':
            return (f"{message.get('files_new', 0)} new and {message.get('files_changed', 0)} changed files, "
                    f"{human_bytes(message.get('data_added', 0))} added in {message.get('total_duration', 0):.0f}s "
                    f"(snapshot {str(message.get('snapshot_id', ''))[:8]}).")
    return ''
