import asyncio
import random
import string
import datetime
import inspect


class Capabilities:
    def __init__(self):
        self.width = 78
        self.height = 24
        self.color = 0
        self.gmcp = False
        self.msdp = False
        self.mssp = False
        self.mccp2 = False
        self.mccp3 = False
        self.ttype = False
        self.naws = False
        self.screen_reader = False
        self.linemode = False
        self.force_endline = False
        self.suppress_ga = True
        self.mouse_tracking = False
        self.utf8 = False
        self.vt100 = False
        self.osc_color_palette = False
        self.proxy = False
        self.mnes = False
        self.client_name = "UNKNOWN"
        self.client_version = "UNKNOWN"
        self.terminal_type = "UNKNOWN"
        self.keepalive = False
        self.mtts = False


class AbstractConnection:

    def __init__(self):
        self.name = None
        self.created = datetime.datetime.utcnow()
        self.capabilities = Capabilities()
        self.host = None
        self.host_port = None
        self.tls = False
        self.protocol = None
        self.on_ready_cb = None
        self.on_command_cb = None
        self.on_oob_cb = None
        self.on_disconnect_cb = None
        self.on_update_cb = None
        self.ready = False
        self.mssp = None

    def export(self):
        return {
            "name": self.name,
            "created": self.created.timestamp(),
            "host": self.host,
            "port": self.host_port,
            "protocol": self.protocol,
            "tls": self.tls,
            "ready": self.ready,
            "capabilities": dict(self.capabilities.__dict__)
        }


class MudConnection(AbstractConnection):

    def __init__(self, listener):
        super().__init__()
        self.listener = listener
        self.task = None
        self.running = False
        self.name = self.generate_name()
        self.created = datetime.datetime.utcnow()
        self.capabilities = Capabilities()
        self.tls = bool(listener.ssl_context)
        self.protocol = listener.protocol

    async def run(self):
        pass

    def start(self):
        if not self.running:
            self.running = True
            self.task = asyncio.create_task(self.run())

    def stop(self):
        if self.task:
            self.task.cancel()
            self.task = None
        self.running = False

    def generate_name(self):
        prefix = f"{self.listener.name}_"

        attempt = f"{prefix}{''.join(random.choices(string.ascii_letters + string.digits, k=20))}"
        while attempt in self.listener.manager.connections:
            attempt = f"{prefix}{''.join(random.choices(string.ascii_letters + string.digits, k=20))}"
        return attempt

    async def on_ready(self):
        if self.ready:
            return
        self.ready = True
        print(f"{self} ready to ready {self.on_ready_cb}")
        if callable(self.on_ready_cb):
            if inspect.iscoroutinefunction(self.on_ready_cb):
                await self.on_ready_cb(self)
            else:
                self.on_ready_cb(self)

    async def close(self):
        pass

    async def on_disconnect(self):
        self.listener.manager.connections.pop(self.name, None)

        if callable(self.on_disconnect_cb):
            if inspect.iscoroutinefunction(self.on_disconnect_cb):
                await self.on_disconnect_cb(self)
            else:
                self.on_disconnect_cb(self)

    async def on_update(self):
        if not self.ready:
            return
        if callable(self.on_update_cb):
            if inspect.iscoroutinefunction(self.on_update_cb):
                await self.on_update_cb(self)
            else:
                self.on_update_cb(self)
