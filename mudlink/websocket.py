import asyncio
from . mudconnection import MudConnection
from websockets.exceptions import ConnectionClosedError, ConnectionClosed, ConnectionClosedOK


class WebSocketConnection(MudConnection):

    def __init__(self, listener, ws, path):
        super().__init__(listener)
        self.connection = ws
        self.path = path
        self.outbox = asyncio.Queue()

    def start(self):
        if not self.running:
            self.running = True
            return self.run()

    async def run(self):
        await asyncio.gather(self.read(), self.write())

    async def read(self):
        try:
            async for message in self.connection:
                await self.process(message)
        except ConnectionClosedError:
            self.running = False
        except ConnectionClosedOK:
            self.running = False
        except ConnectionClosed:
            self.running = False

    async def write(self):
        while self.running:
            msg = await self.outbox.get()
            await self.connection.send(msg)

    async def process(self, msg):
        pass