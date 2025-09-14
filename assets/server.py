from fastapi import FastAPI, Request
from datetime import datetime, timedelta, timezone
import sqlite3
import os
import logging
from misc import setup_logging, import_configuration

app = FastAPI()

script_path=os.path.abspath(os.path.dirname(__file__))
loaded_config = import_configuration(f'{script_path}/../config/server.yaml')
setup_logging(loaded_config, script_path)

db_file = loaded_config['server']['db']
default_backup_interval = loaded_config['server']['default_backup_interval']
logger = logging.getLogger(__name__)
def init_db(db_file):
    if not os.path.exists(db_file):
        logger.info('Initializing database...')
        conn = sqlite3.connect(db_file)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id TEXT PRIMARY KEY,
                last_backup TIMESTAMP,
                backup_interval_hours INTEGER DEFAULT 24,
                last_forget TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    else:
        logger.info('Found existing database...')

init_db(db_file)

@app.post("/register")
async def register(request: Request):
    data = await request.json()
    client_id = data["id"]
    logger.info(f'Client: {client_id}')
    conn = sqlite3.connect(db_file)
    db_connection = conn.cursor()
    db_connection.execute("SELECT last_backup, backup_interval_hours FROM clients WHERE id = ?", (client_id,))
    row = db_connection.fetchone()
    now = datetime.now(timezone.utc)
    action = None
    if row:
        last_backup, interval = row
        interval = interval or default_backup_interval
        if last_backup is None or (now - datetime.fromisoformat(last_backup)) > timedelta(hours=interval):
            action = "backup"
            logger.info(f'A backup is needed...')
    else:
        # New client → default interval
        db_connection.execute("INSERT INTO clients (id, last_backup, backup_interval_hours) VALUES (?, ?, ?)",
                  (client_id, None, default_backup_interval))
        action = "backup"
        logger.info(f'New client, taking a backup...')

    conn.commit()
    conn.close()

    if action != 'backup':
        action = 'ok'
        logger.info('No backup needed.')

    return {"status": "ok", "action": action}

@app.post("/report")
async def report(request: Request):
    data = await request.json()
    client_id = data["id"]
    success = data["success"]

    conn = sqlite3.connect(db_file)
    db_connection = conn.cursor()

    if success:
        now = datetime.now(timezone.utc)
        db_connection.execute("UPDATE clients SET last_backup = ? WHERE id = ?", (now, client_id))
        logger.info(f'Updating last backup timestamp for {client_id} to {now}.')
    conn.commit()
    conn.close()

    return {"status": "ok"}

@app.post("/config")
async def config(request: Request):
    data = await request.json()
    client_id = data["id"]
    interval = int(data.get("backup_interval_hours", default_backup_interval))

    conn = sqlite3.connect(db_file)
    db_connection = conn.cursor()
    db_connection.execute("UPDATE clients SET backup_interval_hours = ? WHERE id = ?", (interval, client_id))
    logger.info(f'Updating configuration for {client_id}.')
    if db_connection.rowcount == 0:
        db_connection.execute("INSERT INTO clients (id, last_backup, backup_interval_hours) VALUES (?, ?, ?)",
                  (client_id, None, interval))
    conn.commit()
    conn.close()

    return {"status": "ok", "id": client_id, "backup_interval_hours": interval}

@app.get("/status")
async def status():
    conn = sqlite3.connect(db_file)
    db_connection = conn.cursor()
    db_connection.execute("SELECT id, last_backup, backup_interval_hours FROM clients")
    rows = db_connection.fetchall()
    conn.close()
    logger.info('Fecthing statuses for all clients:')
    
    clients = []
    now = datetime.now(timezone.utc)

    for cid, last_backup, interval in rows:
        if last_backup:
            last_dt = datetime.fromisoformat(last_backup)
            next_due = last_dt + timedelta(hours=interval)
            overdue = now > next_due
        else:
            last_dt = None
            next_due = None
            overdue = True

        clients.append({
            "id": cid,
            "last_backup": last_backup,
            "backup_interval_hours": interval,
            "next_due": next_due.isoformat() if next_due else None,
            "overdue": overdue
        })
    logger.info(f'{len(clients)} clients found.')
    return {"clients": clients}

@app.post("/forget")
async def forget(request: Request):
    """Client asks if it should run restic forget"""
    data = await request.json()
    client_id = data["id"]

    conn = sqlite3.connect(db_file)
    db_connection = conn.cursor()
    db_connection.execute("SELECT last_forget FROM clients WHERE id = ?", (client_id,))
    row = db_connection.fetchone()

    now = datetime.now(timezone.utc)
    action = "ok"

    if row:
        last_forget = row[0]
        if last_forget is None or (now - datetime.fromisoformat(last_forget)) > timedelta(days=default_backup_interval):
            action = "forget"
    else:
        db_connection.execute("INSERT INTO clients (id, last_backup, backup_interval_hours, last_forget) VALUES (?, ?, ?, ?)",
                  (client_id, None, default_backup_interval, None))
        action = "forget"

    conn.commit()
    conn.close()

    return {"status": "ok", "action": action}

@app.post("/forget/report")
async def forget_report(request: Request):
    """Client reports result of restic forget"""
    data = await request.json()
    client_id = data["id"]
    success = data["success"]

    conn = sqlite3.connect(db_file)
    db_connection = conn.cursor()

    if success:
        now = datetime.now(timezone.utc).isoformat()
        db_connection.execute("UPDATE clients SET last_forget = ? WHERE id = ?", (now, client_id))
    conn.commit()
    conn.close()

    return {"status": "ok"}