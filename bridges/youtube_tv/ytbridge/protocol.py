# SPDX-License-Identifier: GPL-3.0-only
"""Map documented library events to a small local state machine.

No private library methods, video downloads, captions or sponsor services used.
"""
import asyncio
import logging
import math
import time
from pyytlounge import EventListener, State, YtLoungeApi


def quiet_logger():
    logger = logging.getLogger('shiftrelay.youtube_transport')
    logger.disabled = True
    for name in ('pyytlounge', 'pyytlounge.models', 'pyytlounge.events', 'pyytlounge.wrapper'):
        logging.getLogger(name).disabled = True
    return logger


class Transport:
    def __init__(self, api):
        self.api = api
        self.lock = asyncio.Lock()

    async def set_volume(self, value):
        async with self.lock:
            return await self.api.set_volume(value)

    async def skip_ad(self):
        async with self.lock:
            return await self.api.skip_ad()

    async def probe(self):
        async with self.lock:
            return await self.api.get_now_playing()


class Listener(EventListener):
    def __init__(self, clock=time.monotonic):
        super().__init__()
        self.controller = None
        self.clock = clock
        self.last_event = clock()

    async def volume_changed(self, event):
        self.last_event = self.clock()
        if self.controller:
            await self.controller.volume_changed(event.volume, event.muted)

    async def ad_playing_changed(self, event):
        self.last_event = self.clock()
        if self.controller:
            await self.controller.ad(True, event.is_skip_enabled)

    async def ad_state_changed(self, event):
        self.last_event = self.clock()
        if not self.controller:
            return
        if event.ad_state == State.AdSkipped or (event.ad_state == State.Buffering and math.isfinite(event.current_time) and event.current_time > 0):
            await self.controller.ad(False)
        elif event.ad_state == State.Stopped:
            # The dependency maps unrecognized enum values to Stopped. Abstain.
            await self.controller.ad(None)
        else:
            await self.controller.ad(True, event.is_skip_enabled)

    async def playback_state_changed(self, event):
        self.last_event = self.clock()
        if self.controller and event.state in (State.Playing, State.Paused, State.Stopped, State.AdSkipped):
            await self.controller.ad(False)

    async def now_playing_changed(self, event):
        await self.playback_state_changed(event)

    async def disconnected(self, event):
        self.last_event = self.clock()
        if self.controller:
            await self.controller.connection(False)


def make_api(listener=None):
    return YtLoungeApi('ShiftRelay', event_listener=listener, logger=quiet_logger())
