#!/usr/bin/env python3
import os
from pathlib import Path
import secrets

path = Path(__file__).resolve().parents[1] / '.env'
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write('SHIFTRELAY_ADMIN_KEY=' + secrets.token_urlsafe(32) + '\n')
    f.write('SHIFTRELAY_PROXY_AUTH=shiftrelay:' + secrets.token_urlsafe(32) + '\n')
    f.write('SHIFTRELAY_BIND=127.0.0.1\n')
print('Created owner-only .env. It contains separate admin and proxy credentials; keep it private.')
