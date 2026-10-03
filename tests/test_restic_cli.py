import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Fails for any repo whose path contains "broken".
FAKE_RESTIC = f'''#!{sys.executable}
import sys
sys.exit(1 if any('broken' in arg for arg in sys.argv) else 0)
'''

class ResticCliTest(unittest.TestCase):
    '''
    Runs restic.py from a copy of the project so its log file and config stay out of the real checkout.
    '''

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        shutil.copy(f'{root}/restic.py', self.tmp)
        shutil.copytree(f'{root}/assets', f'{self.tmp}/assets', ignore=shutil.ignore_patterns('__pycache__'))
        restic = f'{self.tmp}/restic'
        with open(restic, 'w') as f:
            f.write(FAKE_RESTIC)
        os.chmod(restic, os.stat(restic).st_mode | stat.S_IEXEC)
        os.makedirs(f'{self.tmp}/config')
        with open(f'{self.tmp}/config/config.yml', 'w') as f:
            f.write(f'''restic_path: {restic}
servers:
  good: {{enabled: true, type: local, repo_path: /good, backup_path: /data, password_file: /pw}}
  broken: {{enabled: true, type: local, repo_path: /broken, backup_path: /data, password_file: /pw}}
  disabled: {{enabled: false}}
''')

    def run_cli(self, *args):
        env = {k: v for k, v in os.environ.items() if k != 'RESTIC_WRAPPER_CONFIG'}
        return subprocess.run([sys.executable, f'{self.tmp}/restic.py', *args], capture_output=True, text=True, env=env).returncode

    def test_exit_codes(self):
        self.assertEqual(self.run_cli('--single', 'good', 'backup'), 0)
        self.assertEqual(self.run_cli('--single', 'disabled', 'backup'), 0)
        self.assertEqual(self.run_cli('backup'), 3)
        self.assertEqual(self.run_cli('--single', 'broken', 'forget'), 3)
        self.assertEqual(self.run_cli('--single', 'missing', 'backup'), 1)
        self.assertEqual(self.run_cli('restore'), 1)
        self.assertEqual(self.run_cli('--single', 'good', 'check'), 0)

    def test_missing_config(self):
        os.remove(f'{self.tmp}/config/config.yml')
        self.assertEqual(self.run_cli('backup'), 1)

if __name__ == '__main__':
    unittest.main()
