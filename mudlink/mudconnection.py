import asyncio
import random
import string
import datetime
import inspect


class Capabilities:
    def __init__(self, owner):
        self.width = 78
        self.height = 24
        self.ansi = False
        self.xterm256 = False
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
        self.tls = bool(owner.listener.ssl_context) if owner else False
        self.mouse_tracking = False
        self.utf8 = False
        self.vt100 = False
        self.osc_color_palette = False
        self.proxy = False
        self.truecolor = False
        self.mnes = False
        self.client_name = "UNKNOWN"
        self.client_version = "UNKNOWN"
        self.terminal_type = "UNKNOWN"
        self.mtts = False


class MudConnection:

    def __init__(self, listener):
        self.listener = listener
        self.task = None
        self.running = False
        self.name = self.generate_name()
        self.created = datetime.datetime.utcnow()
        self.capabilities = Capabilities(self)
        self.host = None
        self.host_port = None
        self.on_command_cb = None
        self.on_oob_cb = None
        self.on_disconnect_cb = None
        self.on_update_cb = None
        self.finished = False

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
        while attempt in self.listener.manager.used:
            attempt = f"{prefix}{''.join(random.choices(string.ascii_letters + string.digits, k=20))}"
        return attempt

    async def on_finish(self):
        if self.finished:
            return
        self.finished = True
        await self.listener.manager.announce_conn(self)

    async def on_update(self):
        if not self.finished:
            return
        if callable(self.on_update_cb):
            if inspect.iscoroutinefunction(self.on_update_cb):
                await self.on_update_cb(self)
            else:
                self.on_update_cb(self)