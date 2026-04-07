#!/usr/bin/env python3
"""One-time OAuth2 setup for Google Calendar API.

Usage:
    1. Create OAuth2 credentials in Google Cloud Console
    2. Download as ~/.onlime/credentials.json
    3. Run: python scripts/setup_gcal.py
    4. Browser opens for auth → token saved to ~/.onlime/token.json
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDS_FILE = Path("~/.onlime/credentials.json").expanduser()
TOKEN_FILE = Path("~/.onlime/token.json").expanduser()


def main() -> None:
    # 1. Check credentials.json
    if not CREDS_FILE.exists():
        print(f"credentials.json not found at {CREDS_FILE}")
        print("Download OAuth2 Client ID from Google Cloud Console:")
        print("  https://console.cloud.google.com/apis/credentials")
        print(f"Save as: {CREDS_FILE}")
        sys.exit(1)

    # 2. Check existing token
    creds: Credentials | None = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.valid:
        print(f"Token already valid: {TOKEN_FILE}")
    elif creds and creds.expired and creds.refresh_token:
        print("Refreshing expired token...")
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
        print("Token refreshed.")
    else:
        # 3. Run OAuth flow
        print("Opening browser for Google Calendar authorization...")
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
        creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())
        print(f"Token saved to {TOKEN_FILE}")

    # 4. List accessible calendars
    print("\nAccessible calendars:")
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    calendars = service.calendarList().list().execute()
    for cal in calendars.get("items", []):
        primary = " (primary)" if cal.get("primary") else ""
        print(f"  - {cal['summary']}{primary}  [{cal['id']}]")

    print("\nSetup complete! GCal connector is ready.")


if __name__ == "__main__":
    main()
