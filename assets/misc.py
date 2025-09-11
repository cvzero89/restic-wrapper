import os
import yaml
import logging
from logging.handlers import RotatingFileHandler

def setup_logging(loaded_config, script_path):
    log_path = f'{script_path}/../logs'
    if not os.path.exists(log_path):
        os.makedirs(log_path)
    log_file = loaded_config['logging'].get('log_file', None)
    log_level = loaded_config['logging'].get('log_level', None)
    max_log_size = loaded_config['logging'].get('max_log_size', None)
    backup_count = loaded_config['logging'].get('backup_count', None)
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
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
            config = yaml.safe_load(config_file)
            minimum_config = ['logging']
            if set(minimum_config).issubset(set(list(config.keys()))) is False:
                print(f'Minimum config keys missing: {minimum_config}')
                print(config.keys())
                exit(1)
            return config
    except FileNotFoundError:
        print('Config file not found.')
        exit(1)
    except yaml.YAMLError:
        print(f'Error parsing {config_location}.')
        exit(1)