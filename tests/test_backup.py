import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

from assets.backup import ResticBackup, backup_summary, human_bytes, split_list

# Records its arguments, floods the merged output and exits with FAKE_EXIT.
FAKE_RESTIC = f'''#!{sys.executable}
import json, os, sys
with open(os.environ['FAKE_ARGS'], 'a') as f:
    f.write(json.dumps(sys.argv[1:]) + '\\n')
for i in range(int(os.environ.get('FAKE_FLOOD', '0'))):
    sys.stderr.write(f'warning: cannot read file {{i}}\\n')
if 'backup' in sys.argv:
    print(json.dumps({{'message_type': 'status', 'percent_done': 0.5}}))
    print(json.dumps({{'message_type': 'summary', 'files_new': 2, 'files_changed': 1, 'data_added': 2048,
                      'total_duration': 3.2, 'snapshot_id': 'abcdef1234567890'}}))
sys.exit(int(os.environ.get('FAKE_EXIT', '0')))
'''

def make_config(tmp, **overrides):
    config = {
        'repo_path': f'{tmp}/repo',
        'backup_path': f'{tmp}/my files',
        'type': 'local',
        'password_file': f'{tmp}/pw',
        'options': {'no-scan': True, 'compression': 'auto', 'read-concurrency': False, 'tags': 'a,b'},
        'forget_options': {'daily': 1, 'weekly': 2, 'monthly': 3},
        'exclude': ['*.tmp', '.DS_Store'],
    }
    config.update(overrides)
    return config

class FakeResticTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.restic = f'{self.tmp}/restic'
        with open(self.restic, 'w') as f:
            f.write(FAKE_RESTIC)
        os.chmod(self.restic, os.stat(self.restic).st_mode | stat.S_IEXEC)
        self.args_file = f'{self.tmp}/args'
        env = mock.patch.dict(os.environ, {'FAKE_ARGS': self.args_file, 'FAKE_EXIT': '0', 'FAKE_FLOOD': '0'})
        env.start()
        self.addCleanup(env.stop)
        notify = mock.patch('assets.backup.send_notification')
        self.notify = notify.start()
        self.addCleanup(notify.stop)

    def task(self, **overrides):
        return ResticBackup(make_config(self.tmp, **overrides), self.restic, self.tmp, ntfy_config={'enabled': True})

    def calls(self):
        with open(self.args_file) as f:
            return [json.loads(line) for line in f]

    def run_quietly(self, func, *args):
        with redirect_stdout(StringIO()) as out:
            result = func(*args)
        return result, out.getvalue()

class CommandBuildingTest(FakeResticTestCase):

    def test_repo_strings(self):
        self.assertEqual(self.task(type='sftp', host='u@h').repo(), f'sftp:u@h:{self.tmp}/repo')
        self.assertEqual(self.task(type='s3', repo_path='https://s3/bucket').repo(), 's3:https://s3/bucket')
        self.assertEqual(self.task().repo(), f'{self.tmp}/repo')

    def test_option_parser(self):
        self.assertEqual(self.task().option_parser(), ['--no-scan', '--compression=auto', '--tag', 'a', '--tag', 'b'])
        options = {'read-concurrency': 4, 'tags': ['x']}
        self.assertEqual(self.task(options=options).option_parser(), ['--read-concurrency', '4', '--tag', 'x'])
        self.assertEqual(self.task(options={'read-concurrency': True}).option_parser(), [])
        self.assertEqual(self.task(options=None).option_parser(), [])

    def test_exclude_args(self):
        self.assertEqual(self.task().exclude_args(), ['--exclude', '*.tmp', '--exclude', '.DS_Store'])
        self.assertEqual(self.task(exclude='a, b,').exclude_args(), ['--exclude', 'a', '--exclude', 'b'])
        self.assertEqual(self.task(exclude=None).exclude_args(), [])

    def test_split_list(self):
        self.assertEqual(split_list(None), [])
        self.assertEqual(split_list('a,,b '), ['a', 'b'])
        self.assertEqual(split_list(['a', 1]), ['a', '1'])

    def test_s3_env_is_isolated_per_repo(self):
        for name, key in (('a', 'AAA'), ('b', 'BBB')):
            with open(f'{self.tmp}/{name}.env', 'w') as f:
                f.write(f'AWS_ACCESS_KEY_ID={key}\n')
        first = self.task(type='s3', options={'.env-file': f'{self.tmp}/a.env'})
        second = self.task(type='s3', options={'.env-file': f'{self.tmp}/b.env'})
        self.assertEqual(first.build_env()['AWS_ACCESS_KEY_ID'], 'AAA')
        self.assertEqual(second.build_env()['AWS_ACCESS_KEY_ID'], 'BBB')
        self.assertNotEqual(os.environ.get('AWS_ACCESS_KEY_ID'), 'AAA')

class ActionTest(FakeResticTestCase):

    def test_backup_success_unlocks_and_reports_summary(self):
        result, out = self.run_quietly(self.task().backup)
        self.assertTrue(result)
        unlock, backup = self.calls()
        self.assertEqual(unlock[-1], 'unlock')
        self.assertEqual(backup[-1], f'{self.tmp}/my files')
        self.assertIn('--json', backup)
        self.assertNotIn('percent_done', out)
        message = self.notify.call_args.kwargs['message']
        self.assertIn('2 new and 1 changed files, 2.0 KiB added in 3s (snapshot abcdef12).', message)
        self.assertTrue(self.notify.call_args.kwargs['success'])

    def test_backup_failure(self):
        os.environ['FAKE_EXIT'] = '1'
        result, _ = self.run_quietly(self.task().backup)
        self.assertFalse(result)
        self.assertEqual(self.notify.call_args.kwargs['title'], 'Backup Failed')

    def test_backup_incomplete_snapshot_is_success_with_warning(self):
        os.environ.update(FAKE_EXIT='3', FAKE_FLOOD='20000')
        result, _ = self.run_quietly(self.task().backup)
        self.assertTrue(result)
        self.assertEqual(self.notify.call_args.kwargs['title'], 'Backup Completed With Warnings')

    def test_forget_prunes_with_policy(self):
        result, _ = self.run_quietly(self.task().forget)
        self.assertTrue(result)
        forget = self.calls()[-1]
        self.assertEqual(forget[forget.index('forget'):], ['forget', '--prune', '--keep-daily', '1', '--keep-weekly', '2', '--keep-monthly', '3'])

    def test_check_with_subset(self):
        result, _ = self.run_quietly(self.task(options={'check_read_data_subset': '5%'}).check)
        self.assertTrue(result)
        self.assertEqual(self.calls()[-1][-3:], ['check', '--read-data-subset', '5%'])

    def test_restore_requires_arguments(self):
        result, _ = self.run_quietly(self.task().restore, None, '/tmp/x')
        self.assertFalse(result)
        self.assertFalse(os.path.exists(self.args_file))

    def test_other_splits_command(self):
        result, _ = self.run_quietly(self.task().other, 'ls "latest" /a b')
        self.assertTrue(result)
        self.assertEqual(self.calls()[-1][-4:], ['ls', 'latest', '/a', 'b'])

class HelpersTest(unittest.TestCase):

    def test_human_bytes(self):
        self.assertEqual(human_bytes(512), '512 B')
        self.assertEqual(human_bytes(1536), '1.5 KiB')
        self.assertEqual(human_bytes(3 * 1024 ** 3), '3.0 GiB')

    def test_backup_summary_without_json(self):
        self.assertEqual(backup_summary('plain text\n[not, a, dict]\n'), '')

if __name__ == '__main__':
    unittest.main()
