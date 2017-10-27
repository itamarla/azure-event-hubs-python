# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Async APIs.

"""

import queue
import asyncio
from threading import Lock
from eventhubs import Receiver, EventData

class AsyncReceiver(Receiver):
    """
    Implements the async API of a L{Receiver}.
    """
    def __init__(self, prefetch=300):
        super(AsyncReceiver, self).__init__(False)
        self.loop = asyncio.get_event_loop()
        self.messages = queue.Queue()
        self.lock = Lock()
        self.link = None
        self.waiter = None
        self.credit = prefetch
        self.delivered = 0

    def on_start(self, link):
        self.link = link
        self.link.flow(300)

    def on_message(self, event):
        """ Handle message received event """
        event_data = EventData.create(event.message)
        self.offset = event_data.offset
        waiter = None
        with self.lock:
            self.credit -= 1
            if self.waiter is None:
                self.messages.put(event_data)
                if self.credit == 0:
                    event.reactor.schedule(0.1, self)
                return
            waiter = self.waiter
            self.waiter = None
            self._on_delivered(1)
        self.loop.call_soon_threadsafe(waiter.set_result, None)

    def on_event_data(self, event_data):
        pass

    def on_timer_task(self, event):
        with self.lock:
            self._on_delivered(0)
            if self.credit == 0 and not self.messages.empty():
                event.reactor.schedule(0.1, self)

    async def receive(self, count):
        """
        Receive events asynchronously.

        @param count: max number of events to receive. The result may be less.

        """
        waiter = None
        batch = []
        while True:
            with self.lock:
                while not self.messages.empty() and count > 0:
                    batch.append(self.messages.get())
                    count -= 1
                    self.delivered += 1
                if batch:
                    return batch
                self.waiter = self.loop.create_future()
                waiter = self.waiter
            await waiter

    def _on_delivered(self, count):
        self.delivered = self.delivered + count
        if self.delivered >= 100:
            self.link.flow(self.delivered)
            self.credit += self.delivered
            self.delivered = 0