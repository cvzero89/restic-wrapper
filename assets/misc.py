import os
import sys
import yaml
import logging
from logging.handlers import RotatingFileHandler

def setup_logging(loaded_config, script_path):
    log_path = f'{script_path}/../logs'
    os.makedirs(log_path, exist_ok=True)
    logging_config = loaded_config.get('logging') or {}
    log_file = logging_config.get('log_file', 'restic.log')
    log_level = logging_config.get('log_level', 'INFO')
    max_log_size = logging_config.get('max_log_size', 5242880)
    backup_count = logging_config.get('backup_count', 5)
    numeric_level = getattr(logging, str(log_level).upper(), logging.INFO)
    log_file_location = f'{log_path}/{log_file}'
    handler = RotatingFileHandler(log_file_location, maxBytes=max_log_size, backupCount=backup_count)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[handler, logging.StreamHandler()]
    )

def import_configuration(config_location):
    try:
        with open(config_location) as config_file:
            config = yaml.safe_load(config_file) or {}
            minimum_config = ['logging']
            if not set(minimum_config).issubset(config.keys()):
                print(f'Minimum config keys missing: {minimum_config}')
                print(config.keys())
                sys.exit(1)
            return config
    except FileNotFoundError:
        print('Config file not found.')
        sys.exit(1)
    except yaml.YAMLError:
        print(f'Error parsing {config_location}.')
        sys.exit(1)