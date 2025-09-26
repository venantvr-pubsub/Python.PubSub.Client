# Get logger for this module (don't configure it)
import logging

from pubsub.config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)
