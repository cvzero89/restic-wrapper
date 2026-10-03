from fastapi import FastAPI, Depends, Header, HTTPException
from pydantic import BaseModel
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Optional
import secrets
import sqlite3
import os
import logging
from misc import setup_logging, import_configuration

script_path=os.path.abspath(os.path.dirname(__file__))
loaded_config = import_configuration(f'{script_path}/../config/server.yaml')
setup_logging(loaded_config, script_path)

server_config = loaded_config['server']
db_file = server_config['db']
default_backup_interval = server_config.get('default_backup_interval', 24)
forget_interval_days = server_config.get('forget_interval_days', 7)
auth_token = server_config.get('auth_token')
logger = logging.getLogger(__name__)

if not auth_token:
    logger.warning('No auth_token set in server.yaml, the API accepts unauthenticated requests.')

def check_token(authorization: Optional[str] = Header(None)):
    '''
    When auth_token is set every request must send "Authorization: Bearer <token>".
    '''
    if auth_token and not secrets.compare_digest(authorization or '', f'Bearer {auth_token}'):
        raise HTTPException(status_code=401, detail='Invalid or missing token.')

app = FastAPI(dependencies=[Depends(check_token)])

class ClientId(BaseModel):
    id: str

class Report(ClientId):
    success: bool

class ClientConfig(ClientId):
    backup_interval_hours: int = default_backup_interval

def connect():
    return closing(sqlite3.connect(db_file))

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def is_due(last_run, interval):
    return last_run is None or (datetime.now(timezone.utc) - datetime.fromisoformat(last_run)) > interval

def init_db():
    '''
    Creates the table if missing and adds columns introduced after the first release.
    '''
    with connect() as conn, conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id TEXT PRIMARY KEY,
                last_backup TIMESTAMP,
                backup_interval_hours INTEGER DEFAULT 24,
                last_forget TIMESTAMP
            )
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(clients)")}
        if 'last_forget' not in columns:
            logger.info('Adding last_forget column to the database...')
            conn.execute("ALTER TABLE clients ADD COLUMN last_forget TIMESTAMP")
    logger.info(f'Database ready at {db_file}.')

init_db()

def ensure_client(conn, client_id):
    conn.execute("INSERT OR IGNORE INTO clients (id, last_backup, backup_interval_hours) VALUES (?, NULL, ?)",
                 (client_id, default_backup_interval))

@app.post("/register")
def register(client: ClientId):
    logger.info(f'Client: {client.id}')
    with connect() as conn, conn:
        ensure_client(conn, client.id)
        last_backup, interval = conn.execute("SELECT last_backup, backup_interval_hours FROM clients WHERE id = ?", (client.id,)).fetchone()

    if is_due(last_backup, timedelta(hours=interval or default_backup_interval)):
        logger.info(f'A backup is needed for {client.id}...')
        return {"status": "ok", "action": "backup"}
    logger.info('No backup needed.')
    return {"status": "ok", "action": "ok"}

@app.post("/report")
def report(result: Report):
    if result.success:
        now = now_iso()
        with connect() as conn, conn:
            conn.execute("UPDATE clients SET last_backup = ? WHERE id = ?", (now, result.id))
        logger.info(f'Updating last backup timestamp for {result.id} to {now}.')
    else:
        logger.warning(f'Client {result.id} reported a failed backup.')
    return {"status": "ok"}

@app.post("/config")
def config(client: ClientConfig):
    with connect() as conn, conn:
        ensure_client(conn, client.id)
        conn.execute("UPDATE clients SET backup_interval_hours = ? WHERE id = ?", (client.backup_interval_hours, client.id))
    logger.info(f'Updating configuration for {client.id}.')
    return {"status": "ok", "id": client.id, "backup_interval_hours": client.backup_interval_hours}

@app.get("/status")
def status():
    with connect() as conn:
        rows = conn.execute("SELECT id, last_backup, backup_interval_hours, last_forget FROM clients").fetchall()
    logger.info('Fetching statuses for all clients:')

    clients = []
    now = datetime.now(timezone.utc)

    for cid, last_backup, interval, last_forget in rows:
        if last_backup:
            next_due = datetime.fromisoformat(last_backup) + timedelta(hours=interval or default_backup_interval)
            overdue = now > next_due
        else:
            next_due = None
            overdue = True

        clients.append({
            "id": cid,
            "last_backup": last_backup,
            "last_forget": last_forget,
            "backup_interval_hours": interval,
            "next_due": next_due.isoformat() if next_due else None,
            "overdue": overdue
        })
    logger.info(f'{len(clients)} clients found.')
    return {"clients": clients}

@app.post("/forget")
def forget(client: ClientId):
    """Client asks if it should run restic forget"""
    with connect() as conn, conn:
        ensure_client(conn, client.id)
        last_forget, = conn.execute("SELECT last_forget FROM clients WHERE id = ?", (client.id,)).fetchone()

    if is_due(last_forget, timedelta(days=forget_interval_days)):
        logger.info(f'A forget is needed for {client.id}...')
        return {"status": "ok", "action": "forget"}
    return {"status": "ok", "action": "ok"}

@app.post("/forget/report")
def forget_report(result: Report):
    """Client reports result of restic forget"""
    if result.success:
        with connect() as conn, conn:
            conn.execute("UPDATE clients SET last_forget = ? WHERE id = ?", (now_iso(), result.id))
        logger.info(f'Updating last forget timestamp for {result.id}.')
    else:
        logger.warning(f'Client {result.id} reported a failed forget.')
    return {"status": "ok"}
