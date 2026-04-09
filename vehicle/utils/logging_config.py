"""
Centralized logging configuration using loguru.
"""
import os
import sys
import logging
import warnings
from loguru import logger
from typing import Any


DEFAULT_LOG_LEVEL = "DEBUG"

# Default format for standard output
DEFAULT_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

# A simpler format for less important logs
SIMPLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<level>{message}</level>"
)

# Module-specific log levels that should be applied
MODULE_LOG_LEVELS = {
    # Azure SDK modules - increase log levels to suppress verbose output
    "azure.core": "WARNING",
    "azure.core.pipeline.policies.http_logging_policy": "ERROR",  # Specifically target HTTP logging
    "azure.identity": "WARNING",
    "azure.cosmos": "WARNING",
    "azure.mgmt": "WARNING",
    "azure.storage": "WARNING",
    
    # Other modules
    "uvicorn": "WARNING", 
    "uvicorn.error": "WARNING",
    "uvicorn.access": "WARNING",
    "asyncio": "WARNING",
    "agent_framework": "INFO",
    "httpx": "WARNING",
    "fastapi": "INFO",
}

# Class to intercept standard library logging and route it through loguru
class InterceptHandler(logging.Handler):
    """
    Intercepts standard library logging and routes it through loguru.
    This is important because Azure SDK uses standard library logging.
    """
    def emit(self, record):
        # Get corresponding loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where the logged message originated
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )

def configure_logging(log_level: str | None = None) -> None:
    """
    Configure loguru logger with the specified settings.

    Args:
        log_level: The default log level to use. If None, uses:
                   LOG_LEVEL env var or DEBUG by default so logger.debug is kept.
    """
    if log_level is None:
        log_level = DEFAULT_LOG_LEVEL

    # First, remove the default configuration
    logger.remove()
    
    # Add a new configuration that writes to stderr with coloring
    logger.add(
        sys.stderr,
        format=DEFAULT_FORMAT,
        level=log_level,
        colorize=True,
        backtrace=True,  # Detailed traceback
        diagnose=True,   # Show variables in traceback
        enqueue=True,    # Thread-safe by using a queue
    )
    
    # Optional: Add a file handler for persistent logging
    log_file = os.getenv("LOG_FILE")
    if log_file:
        logger.add(
            log_file,
            rotation="10 MB",  # Rotate when file reaches 10 MB
            retention="1 week",  # Keep logs for 1 week
            compression="zip",  # Compress rotated logs
            format=DEFAULT_FORMAT,
            level=log_level,  # Will be DEBUG by default unless overridden
            backtrace=True,
            diagnose=True,
            enqueue=True,
        )

    # Intercept standard library logging
    # This is essential because Azure SDK uses the standard logging library
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    
    # Set specific log levels for known modules
    for module, level in MODULE_LOG_LEVELS.items():
        mod_logger = logging.getLogger(module)
        mod_logger.setLevel(getattr(logging, level))

    # Suppress noisy DeprecationWarnings from websockets / uvicorn (default: enabled)
    warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"websockets(\.|$)")
    warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"uvicorn\.protocols\.websockets\.websockets_impl")
    
    # Suppress ALL Pydantic V2.11 deprecation warnings (including from internal modules)
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        message=r".*PydanticDeprecatedSince211.*",
    )
    
    # Suppress Pydantic V2.0 deprecation warnings
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        message=r".*PydanticDeprecatedSince20.*",
    )
    
    # Suppress specific Pydantic internal schema generation warnings
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        module=r"pydantic\._internal\._generate_schema",
    )
    
    # Broader filter for any Pydantic deprecation
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        module=r"pydantic(\.|$)",
    )

# A function to get a logger for a specific module
def get_logger(name: str) -> Any:
    """
    Get a properly configured logger for the given module name.
    
    Args:
        name: The module name
        
    Returns:
        Configured logger instance
    """
    return logger.bind(name=name)

# Export the main logger and configuration function
__all__ = ["logger", "configure_logging", "get_logger"]
