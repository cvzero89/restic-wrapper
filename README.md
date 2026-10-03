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

- Python 3.9+  
- restic installed and configured (repository, credentials).  
- Required Python packages:  
  ```bash
  pip install -r requirements.txt
  ```

---

## Configuration

Copy each example file in `config/` and edit it:

| File | Example | Used by |
|------|---------|---------|
| `config/config.yml` | `config-example.yml` | `restic.py` – repos, backup paths, excludes, forget policy, ntfy. |
| `config/server.yaml` | `server-example.yaml` | `assets/server.py` – database, backup interval (hours), forget interval (days), optional `auth_token`. |
| `config/client.yaml` | `client-example.yaml` | `assets/client.py` – `server_url`, `python_interp`, check interval, optional `auth_token` and `client_id`. |

If `auth_token` is set on the server, every client must use the same value. Without it the API accepts any request, so only expose it on a trusted network.

`restic.py` exits with a non-zero code when any repo fails, which is how the client knows whether to report success. A backup where restic could not read some files (exit code 3) still counts as successful, but you get a warning notification.  

---

## Usage

### Starting the Server

Run from the `assets/` directory:

```bash
cd assets && uvicorn server:app --host 0.0.0.0 --port 8080
```

You can also deploy via systemd:

```ini
# restic-server.service
[Unit]
Description=Restic Orchestrator Server
After=network.target

[Service]
ExecStart=/usr/bin/env uvicorn server:app --host 0.0.0.0 --port 8080
WorkingDirectory=/path/to/restic/assets
Restart=always
User=youruser

[Install]
WantedBy=multi-user.target
```

### Running the Client

Set `server_url` and `python_interp` in `config/client.yaml`; repositories and backup paths come from `config/config.yml`.

```bash
python3 assets/client.py
```

Deploy as a service using systemd:

```ini
# restic-client.service
[Unit]
Description=Restic Backup Client
After=network.target

[Service]
ExecStart=/path/to/restic/venv/bin/python3 /path/to/restic/assets/client.py
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
- **Forget interval**: `forget_interval_days` in `server.yaml`, 7 by default. Even though the client polls every 6 hours, the server only returns the `forget` action once that many days have passed since the last successful forget. Forget runs with `--prune`, so unreferenced data is removed from the repository.

---

