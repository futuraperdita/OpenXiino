import os
import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

def setup_logging():
    """Configure logging based on environment variables."""
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    log_path = os.getenv('LOG_PATH')
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # Remove any existing handlers
    logger.handlers = []
    
    if log_path:
        # Ensure log directory exists
        log_dir = os.path.dirname(log_path)
        if log_dir:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            
        # Create rotating file handler (10MB files, keep 5 backups)
        handler = RotatingFileHandler(
            log_path,
            maxBytes=10*1024*1024,
            backupCount=5
        )
    else:
        # Default to stderr if no log path specified
        handler = logging.StreamHandler(sys.stderr)
    
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# Create module-level loggers
server_logger = logging.getLogger('server')
html_logger = logging.getLogger('html_converter')
image_logger = logging.getLogger('image_converter')
