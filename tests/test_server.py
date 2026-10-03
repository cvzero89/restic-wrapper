import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi import HTTPException

server = None
tmp = tempfile.mkdtemp()
db_file = f'{tmp}/test.db'

def setUpModule():
    '''
    server.py reads its config at import time, so it is imported against a temporary config
    with an old-schema database (no last_forget column) to exercise the migration.
    '''
    global server
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE clients (id TEXT PRIMARY KEY, last_backup TIMESTAMP, backup_interval_hours INTEGER DEFAULT 24)")
        conn.execute("INSERT INTO clients VALUES ('legacy', '2000-01-01 00:00:00.000000+00:00', 24)")
    with open(f'{tmp}/server.yaml', 'w') as f:
        f.write(f"server:\n  db: '{db_file}'\n  default_backup_interval: 24\n  forget_interval_days: 7\n  auth_token: secret\nlogging: {{}}\n")
    with mock.patch.dict(os.environ, {'RESTIC_SERVER_CONFIG': f'{tmp}/server.yaml'}), mock.patch('assets.misc.setup_logging'):
        sys.modules.pop('assets.server', None)
        server = importlib.import_module('assets.server')

def set_column(client_id, column, value):
    with sqlite3.connect(db_file) as conn:
        conn.execute(f"UPDATE clients SET {column} = ? WHERE id = ?", (value, client_id))

def ago(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()

class ServerTest(unittest.TestCase):

    def test_auth_token(self):
        server.check_token('Bearer secret')
        for header in (None, '', 'Bearer wrong', 'secret'):
            with self.assertRaises(HTTPException):
                server.check_token(header)

    def test_migration_adds_last_forget(self):
        with sqlite3.connect(db_file) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(clients)")}
        self.assertIn('last_forget', columns)

    def test_legacy_timestamp_is_due(self):
        self.assertEqual(server.register(server.ClientId(id='legacy'))['action'], 'backup')

    def test_backup_cycle(self):
        client = server.ClientId(id='cycle')
        self.assertEqual(server.register(client)['action'], 'backup')
        server.report(server.Report(id='cycle', success=False))
        self.assertEqual(server.register(client)['action'], 'backup')
        server.report(server.Report(id='cycle', success=True))
        self.assertEqual(server.register(client)['action'], 'ok')
        set_column('cycle', 'last_backup', ago(hours=25))
        self.assertEqual(server.register(client)['action'], 'backup')

    def test_custom_interval(self):
        server.config(server.ClientConfig(id='custom', backup_interval_hours=12))
        set_column('custom', 'last_backup', ago(hours=13))
        self.assertEqual(server.register(server.ClientId(id='custom'))['action'], 'backup')
        set_column('custom', 'last_backup', ago(hours=11))
        self.assertEqual(server.register(server.ClientId(id='custom'))['action'], 'ok')

    def test_forget_runs_every_seven_days(self):
        client = server.ClientId(id='forget')
        self.assertEqual(server.forget(client)['action'], 'forget')
        server.forget_report(server.Report(id='forget', success=True))
        self.assertEqual(server.forget(client)['action'], 'ok')
        set_column('forget', 'last_forget', ago(days=6))
        self.assertEqual(server.forget(client)['action'], 'ok')
        set_column('forget', 'last_forget', ago(days=8))
        self.assertEqual(server.forget(client)['action'], 'forget')

    def test_status(self):
        server.register(server.ClientId(id='status'))
        clients = {c['id']: c for c in server.status()['clients']}
        self.assertTrue(clients['status']['overdue'])
        self.assertIsNone(clients['status']['next_due'])
        self.assertIn('last_forget', clients['status'])

if __name__ == '__main__':
    unittest.main()
