# SPDX-License-Identifier: GPL-3.0-only
"""Native control state machine; never claims that a command removed an ad."""
import asyncio
from pathlib import Path
import time
from .storage import atomic_json, read_json


class Controller:
    def __init__(self, transport, state_dir, screen_fingerprint, mode='observe', allow_skip=False,
                 clock=time.monotonic, wall=time.time, max_silence=60, command_timeout=3):
        if mode not in ('observe', 'assist'):
            raise ValueError('Mode must be observe or assist')
        self.transport, self.mode, self.allow_skip = transport, mode, allow_skip
        self.clock, self.wall = clock, wall
        self.max_silence, self.command_timeout = max_silence, command_timeout
        self.screen_fingerprint = screen_fingerprint
        self.journal_path = Path(state_dir) / 'restore.json'
        self.lock = asyncio.Lock()
        self.connected = False
        self.ad_active = None
        self.skip_enabled = False
        self.volume = None
        self.muted = None
        self.manual_override = False
        self.exhausted = False
        self.started = None
        self.restore_sent_at = None
        self.skip_at = float('-inf')
        self.skip_attempts = 0
        self.pending = None
        self.reason = 'starting'
        self.counters = dict(ad_breaks=0, lower_requests=0, restore_requests=0, skip_requests=0, command_failures=0)
        try:
            pending = read_json(self.journal_path)
            if (not isinstance(pending, dict) or set(pending) != {'volume', 'created_at', 'screen_fingerprint'}
                    or type(pending['volume']) is not int or not 1 <= pending['volume'] <= 100
                    or type(pending['created_at']) not in (int, float)
                    or not isinstance(pending['screen_fingerprint'], str)):
                raise ValueError('Invalid recovery journal')
            self.pending = pending
            self.reason = 'recovery_pending'
        except FileNotFoundError:
            pass

    def snapshot(self):
        return dict(schema=1, adapter='youtube_tv', mode=self.mode, connected=self.connected,
                    ad_active=self.ad_active, skip_enabled=self.skip_enabled,
                    volume_owned=self.started is not None, pending_restore=self.pending is not None,
                    manual_override=self.manual_override, reason=self.reason,
                    counters=self.counters.copy(), updated_at=int(self.wall()))

    async def command(self, name, value=None):
        try:
            operation = getattr(self.transport, name)
            result = await asyncio.wait_for(operation() if value is None else operation(value), self.command_timeout)
            if result is not True:
                raise RuntimeError('Command not accepted')
            return True
        except (Exception, asyncio.TimeoutError):
            # Never log exception text: upstream errors may contain credential-bearing URLs.
            self.counters['command_failures'] += 1
            self.reason = 'command_failed'
            return False

    def forget_restore(self):
        self.pending = None
        self.started = None
        self.restore_sent_at = None
        self.journal_path.unlink(missing_ok=True)

    async def restore(self, recovery=False):
        if self.pending is None:
            return
        if not self.connected or (recovery and self.volume is None):
            self.reason = 'recovery_pending'
            return
        if self.pending['screen_fingerprint'] != self.screen_fingerprint:
            self.reason = 'recovery_device_mismatch'
            return
        if self.restore_sent_at is not None and self.clock() - self.restore_sent_at < 5:
            return
        if recovery and self.volume != 0:
            # User/platform has already restored or changed it; do not overwrite.
            self.forget_restore()
            self.reason = 'volume_already_changed'
            return
        age = self.wall() - self.pending['created_at']
        if recovery and not 0 <= age <= 900:
            self.reason = 'manual_recovery_required'
            return
        target = self.pending['volume']
        if await self.command('set_volume', target):
            self.counters['restore_requests'] += 1
            # Keep write-ahead recovery until an actual volume event confirms a
            # nonzero level. HTTP command acceptance is not proof of TV state.
            self.restore_sent_at = self.clock()
            self.started = None
            self.reason = 'restore_requested'

    async def reconcile(self):
        if not self.connected:
            return
        if self.pending is not None and self.started is None:
            await self.restore(recovery=True)
            if self.pending is not None:
                return
        if self.mode == 'observe' or self.ad_active is not True:
            await self.restore()
            return
        if self.allow_skip and self.skip_enabled and self.skip_attempts < 3 and self.clock() - self.skip_at >= 5:
            self.skip_at = self.clock(); self.skip_attempts += 1
            self.counters['skip_requests'] += 1
            await self.command('skip_ad')
        if (self.manual_override or self.exhausted or self.pending is not None
                or self.volume is None or self.volume <= 0 or self.muted is not False):
            return
        pending = dict(volume=self.volume, created_at=self.wall(), screen_fingerprint=self.screen_fingerprint)
        # Write ahead: a crash/timeout after sending zero must leave a recovery record.
        atomic_json(self.journal_path, pending)
        self.pending = pending
        self.started = self.clock()
        self.volume = None  # The pre-command reading is not a post-command acknowledgement.
        self.counters['lower_requests'] += 1
        if await self.command('set_volume', 0):
            self.reason = 'volume_zero_requested'
        else:
            self.exhausted = True
            # Command may have reached the TV even if the acknowledgement was lost.
            await self.restore()

    async def connection(self, online):
        async with self.lock:
            if not online:
                # Best effort while the current transport may still be connected.
                await self.restore()
                self.connected = False
                self.ad_active = None; self.skip_enabled = False
                self.volume = self.muted = None
                self.started = None
                self.reason = 'disconnected' if self.pending is None else 'recovery_pending'
            else:
                self.connected = True
                self.reason = 'observing' if self.mode == 'observe' else 'ready'
                await self.reconcile()

    async def ad(self, active, skip_enabled=False):
        if active is not None and type(active) is not bool:
            raise ValueError('Boolean or unknown ad state required')
        if type(skip_enabled) is not bool:
            raise ValueError('Boolean skip state required')
        async with self.lock:
            if active is True and self.ad_active is not True:
                self.counters['ad_breaks'] += 1
                self.skip_attempts = 0; self.skip_at = float('-inf')
            self.ad_active, self.skip_enabled = active, skip_enabled if active else False
            if active is not True:
                await self.restore()
                self.manual_override = self.exhausted = False
            await self.reconcile()

    async def volume_changed(self, volume, muted):
        if type(volume) is not int or not 0 <= volume <= 100 or type(muted) is not bool:
            raise ValueError('Invalid volume state')
        async with self.lock:
            self.volume, self.muted = volume, muted
            if self.restore_sent_at is not None and volume != 0:
                self.manual_override = volume != self.pending['volume']
                self.forget_restore()
                self.reason = 'volume_restore_confirmed'
            elif self.started is not None and volume != 0:
                # A nonzero report after our zero request is an explicit change. Respect it.
                self.manual_override = True
                self.forget_restore()
                self.reason = 'manual_volume_override'
            await self.reconcile()

    async def tick(self):
        async with self.lock:
            if self.started is not None and self.clock() - self.started >= self.max_silence:
                self.exhausted = True
                await self.restore()
                if self.pending is None:
                    self.reason = 'silence_budget_expired'
