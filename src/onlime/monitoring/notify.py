"""macOS notifications and error alerts."""
from __future__ import annotations

import subprocess
import logging

logger = logging.getLogger(__name__)


def notify(title: str, message: str) -> None:
    """Send a macOS notification."""
    try:
        subprocess.run([
            'osascript', '-e',
            f'display notification "{message}" with title "{title}"'
        ], capture_output=True, timeout=5)
    except Exception as e:
        logger.debug(f"Notification failed: {e}")


def notify_error(message: str) -> None:
    """Send an error notification."""
    notify("Onlime 오류", message)


def notify_success(message: str) -> None:
    """Send a success notification."""
    notify("Onlime", message)
