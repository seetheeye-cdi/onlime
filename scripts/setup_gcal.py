#!/usr/bin/env python3
"""Google Calendar OAuth2 setup helper.

Wrapper that calls: onlime setup gcal
"""
import subprocess
import sys

if __name__ == '__main__':
    sys.exit(subprocess.call([sys.executable, '-m', 'onlime.cli', 'setup', 'gcal']))
