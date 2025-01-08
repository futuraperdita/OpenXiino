import os
import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

def setup_logging():
    """Configure logging based on environment variables."""
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    log_path = os.getenv('LOG_PATH')
    
    # Create formatter with microsecond precision
    formatter = logging.Formatter(
        '%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove any existing handlers
    root_logger.handlers = []
    
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
    root_logger.addHandler(handler)

# Create module-level loggers and ensure they inherit from root
server_logger = logging.getLogger('server')
html_logger = logging.getLogger('html_converter')
image_logger = logging.getLogger('image_converter')
color_logger = logging.getLogger('color_matching')
dither_logger = logging.getLogger('dithering')
scanline_logger = logging.getLogger('scanline')
mode9_logger = logging.getLogger('mode9')

# Ensure all our loggers propagate to root and don't filter
LOGGERS = [
    server_logger,
    html_logger,
    image_logger,
    color_logger,
    dither_logger,
    scanline_logger,
    mode9_logger
]

for logger in LOGGERS:
    logger.propagate = True
    logger.setLevel(logging.NOTSET)  # Use root logger's level
