#!/usr/bin/env python3
"""Plaud.ai token setup helper.

Wrapper that calls: onlime setup plaud
"""
import subprocess
import sys

if __name__ == '__main__':
    args = ['setup', 'plaud'] + sys.argv[1:]
    sys.exit(subprocess.call([sys.executable, '-m', 'onlime.cli'] + args))
