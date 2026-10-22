# SPDX-License-Identifier: GPL-3.0-only
"""Pair one opted-in YouTube TV app, observe events, optionally assist playback."""
import argparse
import asyncio
import getpass
import hashlib
import importlib.metadata
import os
from pathlib import Path
import re
import signal
import sys
import time
from . import __version__
from .controller import Controller
from .protocol import Listener, Transport, make_api
from .storage import atomic_json, read_json


def validate_auth(value):
    keys = {'version', 'screenId', 'loungeIdToken', 'refreshToken', 'expiry'}
    if not isinstance(value, dict) or set(value) != keys or type(value['version']) is not int or value['version'] != 0:
        raise ValueError('Unsupported pairing state; pair again')
    if not isinstance(value['screenId'], str) or not 1 <= len(value['screenId']) <= 4096:
        raise ValueError('Invalid screen id')
    for field in ('loungeIdToken', 'refreshToken'):
        if value[field] is not None and (not isinstance(value[field], str) or len(value[field]) > 8192):
            raise ValueError('Invalid token')
    if value['expiry'] is not None and type(value['expiry']) is not int:
        raise ValueError('Invalid expiry')
    return value


def load_auth(path):
    if Path(path).stat().st_mode & 0o077:
        raise ValueError('Pairing file must be owner-only (chmod 600)')
    return validate_auth(read_json(path))


def public_status(path, controller, reason=None):
    value = controller.snapshot()
    if reason is not None:
        value['reason'] = reason
    atomic_json(path, value, mode=0o644)


async def pair(state, replace=False, api_factory=make_api, read_code=getpass.getpass):
    state = Path(state)
    auth_path = state / 'auth.json'
    if (state / 'restore.json').exists():
        raise ValueError('A volume recovery is pending. Restore the TV volume and run the existing pairing before replacing it.')
    if auth_path.exists() and not replace:
        raise ValueError('Pairing already exists. Use pair --replace to pair a different device.')
    if read_code is getpass.getpass and not sys.stdin.isatty():
        raise ValueError('Pair in an interactive terminal so the TV code can remain hidden')
    # Prompt only on this terminal. Never accept a code on the command line or log it.
    code = re.sub(r'[ -]', '', read_code('TV link code (hidden): '))
    if not re.fullmatch(r'[0-9]{12}', code):
        raise ValueError('Use the 12 digit Link with TV code shown in the television YouTube app')
    async with api_factory() as api:
        if not await asyncio.wait_for(api.pair(code), 15):
            raise RuntimeError('Pairing was not accepted')
        # Use the library's current public auth serializer: store_auth_state() returns
        # legacy keys that do not round-trip through load_auth_state() in version 3.4.
        auth = validate_auth(api.auth.serialize())
        atomic_json(auth_path, auth)
    print('Paired one YouTube TV app. Start in observe mode before enabling Assist.')


async def session(state, status_path, mode, allow_skip, stop, api_factory=make_api):
    auth = load_auth(state / 'auth.json')
    listener = Listener()
    async with api_factory(listener) as api:
        api.load_auth_state(auth)
        if not await asyncio.wait_for(api.refresh_auth(), 15):
            raise RuntimeError('Pairing refresh failed')
        atomic_json(state / 'auth.json', validate_auth(api.auth.serialize()))
        fingerprint = hashlib.sha256(api.auth.screen_id.encode()).hexdigest()
        transport = Transport(api)
        controller = Controller(transport, state, fingerprint, mode=mode, allow_skip=allow_skip)
        listener.controller = controller
        subscription = None
        try:
            if not await asyncio.wait_for(api.connect(), 15):
                raise RuntimeError('Connection was not accepted')
            listener.last_event = time.monotonic()
            await controller.connection(True)
            public_status(status_path, controller)
            subscription = asyncio.create_task(api.subscribe())
            next_probe = time.monotonic() + 10
            while not stop.is_set() and not subscription.done():
                await controller.tick()
                now = time.monotonic()
                if now - listener.last_event > 35:
                    controller.reason = 'events_stale'
                    break
                if now >= next_probe:
                    next_probe = now + 10
                    if not await controller.command('probe'):
                        break
                public_status(status_path, controller)
                try:
                    await asyncio.wait_for(stop.wait(), 1)
                except asyncio.TimeoutError:
                    pass
            if subscription.done() and not subscription.cancelled():
                subscription.result()
        finally:
            await controller.connection(False)
            public_status(status_path, controller)
            if subscription is not None:
                subscription.cancel()
                await asyncio.gather(subscription, return_exceptions=True)
            if api.connected():
                try:
                    await asyncio.wait_for(api.disconnect(), 3)
                except Exception:
                    pass


async def run(state, status_path, mode, allow_skip, once=False):
    state = Path(state); state.mkdir(parents=True, exist_ok=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    delay = 2
    while not stop.is_set():
        blank = Controller(None, state, 'unpaired', mode=mode, allow_skip=allow_skip)
        if not (state / 'auth.json').exists():
            public_status(status_path, blank, 'awaiting_pairing')
        else:
            try:
                await session(state, status_path, mode, allow_skip, stop)
                delay = 2
            except Exception:
                # Do not print exception messages, device names, media IDs or auth data.
                public_status(status_path, blank, 'connection_failed')
                delay = min(delay * 2, 30)
        if once or stop.is_set():
            return
        try:
            await asyncio.wait_for(stop.wait(), delay)
        except asyncio.TimeoutError:
            pass


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__, epilog='Optional GPL-3.0-only bridge; no warranty. See NOTICE.md and LICENSE.')
    parser.add_argument('--state-dir', type=Path, default=Path(os.environ.get('SHIFTRELAY_TV_STATE', '/state')))
    parser.add_argument('--status-path', type=Path, default=Path(os.environ.get('SHIFTRELAY_TV_STATUS', '/status/youtube-tv.json')))
    commands = parser.add_subparsers(dest='command', required=True)
    pairing = commands.add_parser('pair'); pairing.add_argument('--replace', action='store_true')
    runtime = commands.add_parser('run')
    runtime.add_argument('--mode', choices=['observe', 'assist'], default=os.environ.get('SHIFTRELAY_TV_MODE', 'observe'))
    runtime.add_argument('--allow-skip', action='store_true', default=os.environ.get('SHIFTRELAY_TV_ALLOW_SKIP', 'false') == 'true')
    runtime.add_argument('--once', action='store_true', help='One loop for installation smoke tests')
    commands.add_parser('doctor')
    args = parser.parse_args()
    try:
        if args.command == 'pair':
            asyncio.run(pair(args.state_dir, args.replace))
        elif args.command == 'run':
            if args.mode not in ('observe', 'assist'):
                parser.error('SHIFTRELAY_TV_MODE must be observe or assist')
            asyncio.run(run(args.state_dir, args.status_path, args.mode, args.allow_skip, args.once))
        else:
            print('ShiftRelay YouTube TV bridge', __version__)
            print('pyytlounge', importlib.metadata.version('pyytlounge'))
            print('Pairing file present:', (args.state_dir / 'auth.json').is_file())
            print('Live-device compatibility: unvalidated; no device commands were sent by doctor')
    except (KeyboardInterrupt, EOFError):
        pass
    except Exception:
        parser.exit(1, 'Operation failed. Check the TV link code, owner-only state files and network access. No secret details were logged.\n')


if __name__ == '__main__':
    main()
