# restic-wrapper + orchestrator

An extension to **restic-wrapper** that adds client‑server orchestration.  
You have a central server tracking clients, backups, and weekly pruning (`restic forget`), and clients that register, back up, prune when needed, and report their status.

---

## Table of Contents

- [Features](#features)  
- [Architecture](#architecture)  
- [Installation](#installation)  
- [Configuration](#configuration)  
- [Usage](#usage)  
- [Endpoints](#endpoints)  
- [Database Schema](#database-schema)  
- [Systemd Services](#systemd-services)  

---

## Features

- All functionality in **restic-wrapper** (init, backup, restore, list snapshots, forget, mount) remains usable.  
- Server‑client additions:  
  - Clients register periodically (every 6 hours) to tell server “I exist / I’m alive”.  
  - Server decides when each client should run a backup based on a configurable interval.  
  - Server also controls weekly runs of `restic forget` (pruning) per client.  
- Clients report success/failure for backups and pruning.  
- Server has per‑client configuration (backup interval, last backup, last forget).  
- Status endpoint to view all clients, their last backup / forget, next due, and if overdue.

---

## Architecture

```
+------------------+           +--------------------------+
|      Client      |           |         Server           |
|------------------|           |--------------------------|
| ‑ Every 6h:      | → /register                   |
|     • register   |           |   Track last_backup,      |
|     • check if   | ← get “backup” / “ok”         |
|       backup     |           |   backup_interval_hours    |
|     • run backup |           |                            |
|     • report     | → /report                     |
|   Weekly:        | → /forget  (if needed)         |
|     • check prune| ← get “forget” / “ok”          |
|     • run forget | → /forget/report              |
|------------------|           | GET /status               |
+------------------+           +--------------------------+
```

- Server: built with FastAPI, stores client state in SQLite.  
- Client: simple Python script, periodic loop.  

---

## Installation

### Prerequisites

- Python 3.8+  
- restic installed and configured (repository, credentials).  
- Required Python packages:  
  ```bash
  pip install fastapi uvicorn requests pyyaml
  ```

---

## Configuration

- **restic-wrapper** config files still present (e.g. `config/config.yml`, `excludes.txt`) for your existing backup/restore behavior.  
- New configuration (server‑client) done in server parameters (port, default intervals), and client settings (restic repository path, commands).  

---

## Usage

### Starting the Server

```bash
uvicorn server:app --host 0.0.0.0 --port 8080
```

You can also deploy via systemd:

```ini
# restic-server.service
[Unit]
Description=Restic Orchestrator Server
After=network.target

[Service]
ExecStart=/usr/bin/env uvicorn server:app --host 0.0.0.0 --port 8080
WorkingDirectory=/path/to/restic-wrapper/orchestrator
Restart=always
User=youruser

[Install]
WantedBy=multi-user.target
```

### Running the Client

Edit `client.py` to set:

- `SERVER_URL`
- Your restic repository and backup paths  
- (Optional) `FORGET_CMD` if using pruning

Deploy as a service using systemd:

```ini
# restic-client.service
[Unit]
Description=Restic Backup Client
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/client.py
Restart=always
User=youruser

[Install]
WantedBy=multi-user.target
```

---

## Endpoints

| Endpoint             | Method | Purpose |
|----------------------|--------|---------|
| `/register`          | POST   | Client announces itself; server returns action (`backup` or `ok`). |
| `/report`            | POST   | Client reports result of a backup. |
| `/forget`            | POST   | Client asks if it should run `restic forget`. |
| `/forget/report`     | POST   | Client reports result of `forget`. |
| `/config`            | POST   | Set per‑client backup interval hours. |
| `/status`            | GET    | List all clients, last backup, last forget, next due, if overdue. |

---

## Database Schema

SQLite table `clients` with columns:

| Column               | Type        | Description |
|----------------------|-------------|-------------|
| `id`                 | TEXT (PK)   | Client identifier (hostname, UUID, etc.). |
| `last_backup`        | TIMESTAMP   | When the last successful backup ran. |
| `backup_interval_hours` | INTEGER | How often backups should run. |
| `last_forget`        | TIMESTAMP   | When last prune / `restic forget` succeeded. |

The server uses these to decide whether to instruct a client to run a backup or forget operation.

---

## Policies

- **Backup interval**: Default is 24 hours unless configured per client.  
- **Forget interval**: Once per week (7 days). Even though client polls every 6 hours, the server only returns `forget` action if 7 days have passed since last successful forget.

---

