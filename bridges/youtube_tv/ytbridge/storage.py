# SPDX-License-Identifier: GPL-3.0-only
"""Bounded JSON files; private pairing and recovery never enter public status."""
import json
import os
from pathlib import Path
import tempfile


def read_json(path, limit=16384):
    with Path(path).open('rb') as file:
        data = file.read(limit + 1)
    if len(data) > limit:
        raise ValueError('State file too large')
    return json.loads(data)


def atomic_json(path, value, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as file:
            json.dump(value, file, allow_nan=False)
            file.write('\n'); file.flush(); os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
