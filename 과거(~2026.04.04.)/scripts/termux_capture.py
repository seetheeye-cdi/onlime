#!/usr/bin/env python3
"""
Termux Notification Capture for Onlime
=======================================

Runs on an Android phone via Termux. Polls KakaoTalk (and other configured
app) notifications and forwards them to the Onlime server for processing.

Prerequisites
-------------
1. Install Termux and Termux:API from F-Droid (NOT Play Store).
2. In Android Settings -> Apps -> Termux:API -> grant Notification Access.
3. Inside Termux, run:
       pkg install termux-api python
       pip install requests

How to run
----------
    python termux_capture.py --server http://192.168.0.X:8000

Set your API key via environment variable (recommended):
    export ONLIME_API_KEY=your_key_here
    python termux_capture.py --server http://192.168.0.X:8000

Or use --dry-run to test without sending anything:
    python termux_capture.py --server http://192.168.0.X:8000 --dry-run

Run once and exit (useful for testing):
    python termux_capture.py --server http://192.168.0.X:8000 --once
"""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print(
        "ERROR: 'requests' is not installed.\n"
        "Run: pip install requests",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration — edit these values or override via CLI arguments / env vars
# ---------------------------------------------------------------------------

SERVER_URL = "http://100.105.205.61:8000"  # Mac Tailscale IP (works anywhere)
API_KEY = os.environ.get("ONLIME_API_KEY", "")  # or paste your key here
DEVICE_ID = "s26ultra"  # identifier for this device
POLL_INTERVAL = 10  # seconds between polls
TARGET_PACKAGES = [
    "com.kakao.talk",
    "com.Slack",
    "org.telegram.messenger",
    "com.instagram.android",
]

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

SEEN_FILE = Path.home() / ".config" / "onlime" / "seen_notifications.json"
SEEN_MAX_AGE_HOURS = 24  # discard IDs older than this to keep file small
INGEST_ENDPOINT = "/api/ingest/notifications"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
log = logging.getLogger("onlime.termux")

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

_running = True


def _handle_signal(signum, frame):
    global _running
    log.info("Shutdown signal received, stopping after current cycle.")
    _running = False


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

# ---------------------------------------------------------------------------
# Seen-notification persistence
# ---------------------------------------------------------------------------


def load_seen_ids() -> dict:
    """Load persisted seen-notification IDs from disk.

    Returns a dict mapping str(id) -> ISO timestamp string of when it was
    first seen. IDs older than SEEN_MAX_AGE_HOURS are pruned on load.
    """
    if not SEEN_FILE.exists():
        return {}
    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=SEEN_MAX_AGE_HOURS)
        pruned = {
            k: v
            for k, v in data.items()
            if _parse_ts(v) is not None and _parse_ts(v) > cutoff
        }
        return pruned
    except Exception as exc:
        log.warning("Could not load seen-IDs file (%s): %s", SEEN_FILE, exc)
        return {}


def save_seen_ids(seen: dict) -> None:
    """Persist seen-notification IDs to disk."""
    try:
        SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        SEEN_FILE.write_text(json.dumps(seen, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        log.warning("Could not save seen-IDs file (%s): %s", SEEN_FILE, exc)


def _parse_ts(ts_str: str):
    """Parse an ISO timestamp string, returning a datetime or None."""
    try:
        return datetime.fromisoformat(ts_str)
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Termux notification polling
# ---------------------------------------------------------------------------


def fetch_notifications() -> list[dict]:
    """Run termux-notification-list and return parsed JSON list.

    Returns an empty list if the command fails or produces no output.
    """
    try:
        result = subprocess.run(
            ["termux-notification-list"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        log.error(
            "termux-notification-list not found. "
            "Is Termux:API installed? Run: pkg install termux-api"
        )
        return []
    except subprocess.TimeoutExpired:
        log.warning("termux-notification-list timed out.")
        return []
    except Exception as exc:
        log.warning("Failed to run termux-notification-list: %s", exc)
        return []

    if result.returncode != 0:
        log.warning(
            "termux-notification-list exited with code %d: %s",
            result.returncode,
            result.stderr.strip(),
        )
        return []

    raw = result.stdout.strip()
    if not raw:
        return []

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        log.warning("Unexpected output format from termux-notification-list.")
        return []
    except json.JSONDecodeError as exc:
        log.warning("Could not parse termux-notification-list output: %s", exc)
        return []


def filter_notifications(notifications: list[dict], packages: list[str]) -> list[dict]:
    """Keep only notifications whose packageName is in the target list."""
    target_set = set(packages)
    return [n for n in notifications if n.get("packageName") in target_set]


# ---------------------------------------------------------------------------
# Payload building
# ---------------------------------------------------------------------------


def build_notification_payload(raw: dict) -> dict:
    """Convert a raw Termux notification dict into Onlime's expected format."""
    # Termux notification fields (may vary by Android version):
    #   id, packageName, tag, title, content (= text), when (ms epoch),
    #   extras (dict with android.* keys)
    extras = raw.get("extras") or {}

    # Prefer android.bigText (full message) over the short content field
    text = extras.get("android.bigText") or raw.get("content") or raw.get("text") or ""
    title = raw.get("title") or ""

    # Timestamp: Termux provides "when" — may be ms-epoch (int) or formatted string
    raw_when = raw.get("when")
    if raw_when is None or raw_when == "":
        timestamp_ms = int(time.time() * 1000)
    elif isinstance(raw_when, (int, float)):
        timestamp_ms = int(raw_when)
    elif isinstance(raw_when, str):
        # Try parsing formatted date strings like "2026-04-02 03:25:56"
        try:
            dt = datetime.strptime(raw_when, "%Y-%m-%d %H:%M:%S")
            timestamp_ms = int(dt.timestamp() * 1000)
        except ValueError:
            try:
                timestamp_ms = int(raw_when)
            except ValueError:
                timestamp_ms = int(time.time() * 1000)
    else:
        timestamp_ms = int(time.time() * 1000)

    # Build a clean extras dict with only the interesting Android keys
    interesting_keys = {
        "android.subText",
        "android.bigText",
        "android.infoText",
        "android.summaryText",
    }
    clean_extras = {k: v for k, v in extras.items() if k in interesting_keys and v}

    return {
        "package": raw.get("packageName", ""),
        "title": title,
        "text": text,
        "timestamp": timestamp_ms,
        "extras": clean_extras,
    }


def build_ingest_request(device_id: str, notifications: list[dict]) -> dict:
    """Build the full IngestRequest payload."""
    return {
        "device_id": device_id,
        "notifications": [build_notification_payload(n) for n in notifications],
    }


# ---------------------------------------------------------------------------
# HTTP sending
# ---------------------------------------------------------------------------


def send_notifications(
    server_url: str,
    api_key: str,
    payload: dict,
    dry_run: bool = False,
) -> bool:
    """POST the payload to the ingest endpoint.

    Returns True on success (or dry-run), False on error.
    """
    url = server_url.rstrip("/") + INGEST_ENDPOINT
    count = len(payload.get("notifications", []))

    if dry_run:
        log.info(
            "[DRY RUN] Would POST %d notification(s) to %s:\n%s",
            count,
            url,
            json.dumps(payload, indent=2, ensure_ascii=False),
        )
        return True

    # Security: warn if sending API key over unencrypted HTTP.
    if api_key and url.startswith("http://") and "127.0.0.1" not in url and "localhost" not in url:
        log.warning(
            "Sending API key over plaintext HTTP to %s. "
            "The key can be intercepted on the network. "
            "Consider using HTTPS or a VPN/SSH tunnel.",
            url,
        )

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        log.warning(
            "Server unreachable at %s — will retry next cycle. "
            "Check that the server is running and SERVER_URL is correct.",
            server_url,
        )
        return False
    except requests.exceptions.Timeout:
        log.warning("Request to %s timed out — will retry next cycle.", url)
        return False
    except requests.exceptions.HTTPError as exc:
        log.warning("Server returned error %s: %s", response.status_code, exc)
        return False
    except Exception as exc:
        log.warning("Unexpected error sending notifications: %s", exc)
        return False

    # Try to log server response details
    try:
        resp_data = response.json()
        accepted = resp_data.get("accepted", count)
        duplicates = resp_data.get("duplicates", 0)
        log.info(
            "Sent %d notification(s) -> accepted=%s duplicates=%s",
            count,
            accepted,
            duplicates,
        )
    except Exception:
        log.info("Sent %d notification(s) -> HTTP %d", count, response.status_code)

    return True


# ---------------------------------------------------------------------------
# Main poll cycle
# ---------------------------------------------------------------------------


def run_poll_cycle(
    server_url: str,
    api_key: str,
    device_id: str,
    packages: list[str],
    seen: dict,
    dry_run: bool,
) -> None:
    """Fetch notifications, deduplicate, and send new ones."""
    all_notifications = fetch_notifications()
    if not all_notifications:
        log.debug("No notifications returned.")
        return

    relevant = filter_notifications(all_notifications, packages)
    if not relevant:
        log.debug("No relevant notifications (checked %d total).", len(all_notifications))
        return

    # Deduplicate against seen set using ID + content hash.
    # KakaoTalk reuses the same notification ID for a chat room, updating
    # only the content.  We detect changes by hashing title + content + when.
    import hashlib

    def _content_fingerprint(n: dict) -> str:
        parts = f"{n.get('title', '')}\x00{n.get('content', '')}\x00{n.get('when', '')}"
        return hashlib.sha256(parts.encode()).hexdigest()[:16]

    unseen = []
    for notif in relevant:
        notif_id = str(notif.get("id", ""))
        fp = _content_fingerprint(notif)
        seen_key = f"{notif_id}:{fp}" if notif_id else fp
        if not notif_id:
            unseen.append(notif)
            continue
        if seen_key not in seen:
            unseen.append(notif)
            # Store fingerprinted key so we use it when marking as seen
            notif["_seen_key"] = seen_key

    log.info(
        "Found %d relevant notification(s), %d new (unseen).",
        len(relevant),
        len(unseen),
    )

    if not unseen:
        return

    payload = build_ingest_request(device_id, unseen)
    success = send_notifications(server_url, api_key, payload, dry_run=dry_run)

    if success:
        # Mark as seen only after successful send
        now = _now_iso()
        for notif in unseen:
            seen_key = notif.get("_seen_key", "")
            if seen_key:
                seen[seen_key] = now
        save_seen_ids(seen)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture KakaoTalk notifications and forward them to the Onlime server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--server",
        default=SERVER_URL,
        metavar="URL",
        help=f"Onlime server base URL (default: {SERVER_URL})",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=POLL_INTERVAL,
        metavar="SECONDS",
        help=f"Seconds between polls (default: {POLL_INTERVAL})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent without actually sending anything.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll cycle then exit (useful for testing).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    server_url = args.server
    interval = args.interval
    dry_run = args.dry_run

    # Warn if the server URL still has the placeholder
    if "192.168.0.X" in server_url:
        log.warning(
            "SERVER_URL contains placeholder '192.168.0.X'. "
            "Pass the real IP with --server http://192.168.0.Y:8000"
        )

    if not API_KEY and not dry_run:
        log.warning(
            "No API key configured. Set ONLIME_API_KEY env var or edit API_KEY in this script."
        )

    mode = "dry-run" if dry_run else "live"
    log.info(
        "Starting Onlime Termux capture | server=%s | device=%s | packages=%s | interval=%ds | mode=%s",
        server_url,
        DEVICE_ID,
        TARGET_PACKAGES,
        interval,
        mode,
    )

    seen = load_seen_ids()
    log.info("Loaded %d previously seen notification ID(s).", len(seen))

    cycle = 0
    while _running:
        cycle += 1
        log.debug("Poll cycle #%d", cycle)
        try:
            run_poll_cycle(
                server_url=server_url,
                api_key=API_KEY,
                device_id=DEVICE_ID,
                packages=TARGET_PACKAGES,
                seen=seen,
                dry_run=dry_run,
            )
        except Exception as exc:
            log.error("Unexpected error in poll cycle: %s", exc, exc_info=True)

        if args.once:
            log.info("--once flag set, exiting after single cycle.")
            break

        if _running:
            log.debug("Sleeping %d seconds.", interval)
            # Sleep in small increments so SIGINT is handled promptly
            deadline = time.monotonic() + interval
            while _running and time.monotonic() < deadline:
                time.sleep(min(1.0, deadline - time.monotonic()))

    log.info("Onlime Termux capture stopped.")


if __name__ == "__main__":
    main()
