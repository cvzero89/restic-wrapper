# restic-wrapper
Python wrapper for restic to push backups, restores, etc to multiple locations.

### Actions

```
init: python3 restic.py init --single <name_in_config_file>
Backup: python3 restic.py backup
List snapshots: python3 restic.py snapshots
Forget: python3 restic.py forget
Mount: python3 restic.py mount --single <name_in_config_file> --restore_path <local_path>
Restore: python3 restic.py restore --single <name_in_config_file> --snapshot_id <ID> --restore_path <local_path>
```

### Config files:
Located in config/ on the script folder: <br>
config.yml <br>
<password_file> → Defined in config.yml <br>
<S3_environment> → Defined in config.yml <br>
excludes.txt → Created automatically based on what is set to config.yml
