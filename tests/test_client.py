import subprocess
import unittest
from unittest import mock

from assets import client

def response(action):
    resp = mock.Mock()
    resp.json.return_value = {'status': 'ok', 'action': action}
    return resp

class RunJobTest(unittest.TestCase):

    def run_job(self, action, run_side_effect=None, job='backup'):
        with mock.patch.object(client.requests, 'post', side_effect=[response(action), mock.Mock()]) as post, \
             mock.patch.object(client.subprocess, 'run', side_effect=run_side_effect) as run, \
             mock.patch.object(client, 'send_notification') as notify:
            client.run_job('http://server', 'c1', ['restic.py', job], job, {'Authorization': 'Bearer t'}, {'enabled': True})
        return post, run, notify

    def test_nothing_due(self):
        post, run, notify = self.run_job('ok')
        run.assert_not_called()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs['headers'], {'Authorization': 'Bearer t'})

    def test_success_is_reported(self):
        post, run, notify = self.run_job('backup')
        run.assert_called_once()
        self.assertEqual(post.call_args.args[0], 'http://server/report')
        self.assertEqual(post.call_args.kwargs['json'], {'id': 'c1', 'success': True})
        notify.assert_not_called()

    def test_repo_failure_reported_without_duplicate_notification(self):
        error = subprocess.CalledProcessError(client.EXIT_REPO_FAILED, 'restic.py')
        post, run, notify = self.run_job('forget', error, job='forget')
        self.assertEqual(post.call_args.args[0], 'http://server/forget/report')
        self.assertEqual(post.call_args.kwargs['json'], {'id': 'c1', 'success': False})
        notify.assert_not_called()

    def test_unexpected_failure_notifies(self):
        post, run, notify = self.run_job('backup', subprocess.CalledProcessError(1, 'restic.py'))
        self.assertEqual(post.call_args.kwargs['json'], {'id': 'c1', 'success': False})
        notify.assert_called_once()

    def test_server_unreachable(self):
        with mock.patch.object(client.requests, 'post', side_effect=ConnectionError('down')), \
             mock.patch.object(client.subprocess, 'run') as run:
            client.run_job('http://server', 'c1', ['x'], 'backup', {})
        run.assert_not_called()

if __name__ == '__main__':
    unittest.main()
