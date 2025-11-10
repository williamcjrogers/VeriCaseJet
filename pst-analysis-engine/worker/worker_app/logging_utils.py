"""
Logging utilities for secure log handling
Prevents log injection attacks (CWE-117, CWE-93)
"""
import logging
import re


def sanitize_for_log(value: str | None) -> str:
    """
    Sanitize user input for safe logging.
    Removes newlines, carriage returns, and control characters to prevent log injection.
    
    Args:
        value: User-controlled string to sanitize
        
    Returns:
        Sanitized string safe for logging
    """
    if not value:
        return ""
    
    # Convert to string if needed
    value_str = str(value)
    
    # Remove newlines and carriage returns
    value_str = value_str.replace('\n', ' ').replace('\r', ' ')
    
    # Remove other control characters (0x00-0x1F except space)
    value_str = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', value_str)
    
    # Truncate to reasonable length
    if len(value_str) > 200:
        value_str = value_str[:197] + '...'
    
    return value_str


class SanitizingFormatter(logging.Formatter):
    """
    Custom formatter that sanitizes log messages to prevent injection attacks.
    Automatically cleans all log records before formatting.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        # Sanitize the message
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            record.msg = sanitize_for_log(record.msg)
        
        # Sanitize args if present
        if hasattr(record, 'args') and record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    sanitize_for_log(arg) if isinstance(arg, str) else arg
                    for arg in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: sanitize_for_log(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
        
        return super().format(record)


def install_log_sanitizer():
    """
    Install sanitizing formatter on all handlers for the root logger.
    Call this once during application startup.
    """
    root_logger = logging.getLogger()
    
    # Create sanitizing formatter
    formatter = SanitizingFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Apply to all existing handlers
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)
    
    # If no handlers exist yet, add a console handler with sanitizing formatter
    if not root_logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
