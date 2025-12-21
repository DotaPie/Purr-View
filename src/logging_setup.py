import logging
import logging.config
from datetime import datetime as dt
import os
from logging.handlers import TimedRotatingFileHandler
import json
from pathlib import Path

# CONF
with open(os.path.join(os.path.dirname((os.path.abspath(__file__))), "config.json"), "r") as f:
    config = json.load(f)

LOGGING_PATH = Path(os.path.expandvars(config["LOGGING_PATH"])).expanduser() # deals with $USER and ~/... 
LOGGING_LEVEL = config["LOGGING_LEVEL"]
LOGGING_ROOT_LEVEL = config["LOGGING_ROOT_LEVEL"]
LOGGING_FILE_NAME = config["LOGGING_FILE_NAME"]
LOGGING_FILE_COUNT = config["LOGGING_FILE_COUNT"]
LOGGING_ROLLOVER_TIME = config["LOGGING_ROLLOVER_TIME"]

class MicrosecondFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        ts = dt.fromtimestamp(record.created)
        return ts.strftime(datefmt or "%Y-%m-%d_%H-%M-%S_%f")

LOG_CONF = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "micro": {
            "()": MicrosecondFormatter,
            "format": "[%(levelname)s] [%(asctime)s] %(message)s",
            "datefmt": "%Y-%m-%d_%H-%M-%S_%f"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": LOGGING_LEVEL,
            "formatter": "micro",
            "stream": "ext://sys.stdout"
        },
        "file": {                                             
            "class": "logging.handlers.TimedRotatingFileHandler",
            "level": LOGGING_LEVEL,
            "formatter": "micro",
            "filename": os.path.join(LOGGING_PATH, LOGGING_FILE_NAME),
            "when": LOGGING_ROLLOVER_TIME,
            "backupCount": LOGGING_FILE_COUNT,
            "encoding": "utf-8",
        }
    },
    "root": {
        "level": LOGGING_ROOT_LEVEL,
        "handlers": ["console", "file"]                       
    },
    "loggers": {
        "purrview": {
            "level": LOGGING_LEVEL,
            "handlers": ["console", "file"],
            "propagate": False
        }
    }
}

def _setup_logging():
    os.makedirs(LOGGING_PATH, exist_ok=True)
    logging.config.dictConfig(LOG_CONF)

def get_logger(name: str = "purrview") -> logging.Logger:
    _setup_logging()
    return logging.getLogger(name)