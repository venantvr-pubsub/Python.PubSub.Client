import logging

from .config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)
