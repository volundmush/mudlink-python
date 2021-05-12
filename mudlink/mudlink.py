import asyncio
import ssl
import inspect
import websockets
from . telnet import TelnetMudConnection
from . websocket import WebSocketConnection


class MudListener:

    def __init__(self, manager, name, interface, port, protocol, ssl_context=None):
        self.manager = manager
        self.name = name
        self.interface = interface
        self.port = port
        self.protocol = protocol
        self.ssl_context = ssl_context
        self.task = None
        self.running = False
        self.server = None

    async def run(self):
        if self.protocol == "telnet":
            self.server = await asyncio.start_server(self.accept_telnet, host=self.interface, port=self.port,
                                                     ssl=self.ssl_context)
        elif self.protocol == "websocket":
            self.server = await websockets.serve(self.accept_websocket, self.interface, self.port, ssl=self.ssl_context)

    def start(self):
        if not self.running:
            self.running = True
            self.task = asyncio.create_task(self.run())

    def stop(self):
        if self.task:
            self.task.cancel()
            self.task = None
        self.running = False

    def accept_telnet(self, reader, writer):
        conn = TelnetMudConnection(self, reader, writer)
        conn.start()

    def accept_websocket(self, ws, path):
        conn = WebSocketConnection(self, ws, path)
        return conn.start()


class MudLinkManager:

    def __init__(self):
        self.ssl_contexts = dict()
        self.listeners = dict()
        self.pending = dict()
        self.connections = dict()
        self.used = set()
        self.interfaces = {
            "localhost":  "127.0.0.1",
            "any": "0.0.0.0",
        }
        self.on_connect_cb = None

    def register_listener(self, name, interface, port, protocol, ssl_context=None):
        if name in self.listeners:
            raise ValueError(f"A Listener is already using name: {name}")
        host = self.interfaces.get(interface, None)
        if not host:
            raise ValueError(f"Interface not registered: {interface}")
        if port < 0 or port > 65535:
            raise ValueError(f"Invalid port: {port}. Port must be number between 0 and 65535")
        if protocol.lower() not in ("telnet", "websocket"):
            raise ValueError(f"Unsupported protocol: {protocol}. Please pick telnet or websocket")
        ssl = self.ssl_contexts.get(ssl_context, None)
        if ssl_context and not ssl:
            raise ValueError(f"SSL Context not registered: {ssl_context}")
        self.listeners[name] = MudListener(self, name, host, port, protocol.lower(), ssl_context=ssl)

    def register_interface(self, name, interface):
        pass

    def register_ssl(self, name, pem_path):
        pass

    def listen(self):
        for k, v in self.listeners.items():
            if not v.task:
                v.task = asyncio.create_task(v.run())

    def stop(self):
        for k, v in self.listeners.items():
            if v.running:
                v.stop()

    async def start(self):
        self.listen()
        await self.run()

    async def run(self):
        while True:
            await asyncio.sleep(5)

    async def announce_conn(self, conn):
        if callable(self.on_connect_cb):
            if inspect.iscoroutinefunction(self.on_connect_cb):
                await self.on_connect_cb(conn)
            else:
                self.on_connect_cb(conn)