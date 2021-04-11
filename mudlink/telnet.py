import asyncio
import zlib
import inspect
from .mudconnection import MudConnection
from typing import Dict

class _TC:
    NULL = 0
    BEL = 7
    CR = 13
    LF = 10
    SGA = 3
    TELOPT_EOR = 25
    NAWS = 31
    LINEMODE = 34
    EOR = 239
    SE = 240
    NOP = 241
    GA = 249
    SB = 250
    WILL = 251
    WONT = 252
    DO = 253
    DONT = 254
    IAC = 255

    # MNES: Mud New-Environ Standard
    MNES = 39

    # MXP: Mud eXtension Protocol
    MXP = 91

    # MSSP: Mud Server Status Protocol
    MSSP = 70

    # MCCP - Mud Client Compression Protocol
    MCCP2 = 86
    MCCP3 = 87

    # GMCP: Generic Mud Communication Protocol
    GMCP = 201

    # MSDP: Mud Server Data Protocol
    MSDP = 69

    # TTYPE - Terminal Type
    TTYPE = 24


NEGOTIATORS = (_TC.WILL, _TC.WONT, _TC.DO, _TC.DONT)
ACK_OPPOSITES = {_TC.WILL: _TC.DO, _TC.DO: _TC.WILL}
NEG_OPPOSITES = {_TC.WILL: _TC.DONT, _TC.DO: _TC.WONT}


class TelnetOutMessage:
    def __init__(self, data):
        self.data = data
        self.enable_compress2 = False
        self.close = False


class TelnetOptionPerspective:

    def __init__(self, owner):
        self.owner = owner
        self.enabled = False
        self.negotiating = False
        self.heard_answer = False
        self.asked = False


class TelnetHandshakeHolder:

    def __init__(self, owner):
        self.owner = owner
        self.local = set()
        self.remote = set()
        self.special = set()

    def has_remaining(self):
        return self.local or self.remote or self.special


class TelnetOptionHandler:
    opcode = 0
    support_local = False
    support_remote = False
    start_will = False
    start_do = False
    hs_local = []
    hs_remote = []
    hs_special = []

    def __init__(self, owner):
        self.owner = owner
        self.local = TelnetOptionPerspective(self)
        self.remote = TelnetOptionPerspective(self)

    async def subnegotiate(self, data):
        pass

    async def negotiate(self, cmd):
        if cmd == _TC.WILL:
            if self.support_remote:
                if self.remote.negotiating:
                    self.remote.negotiating = False
                    if not self.remote.enabled:
                        self.remote.enabled = True
                        await self.owner.send_negotiate(_TC.DO, self.opcode)
                        await self.enable_remote()
                        if self.opcode in self.owner.handshakes.remote:
                            self.owner.handshakes.remote.remove(self.opcode)
                            await self.owner.check_ready()
                else:
                    self.remote.enabled = True
                    await self.owner.send_negotiate(_TC.DO, self.opcode)
                    await self.enable_remote()
                    if self.opcode in self.owner.handshakes.remote:
                        self.owner.handshakes.remote.remove(self.opcode)
                        await self.owner.check_ready()
            else:
                await self.owner.send_negotiate(_TC.DONT, self.opcode)

        elif cmd == _TC.DO:
            if self.support_local:
                if self.local.negotiating:
                    self.local.negotiating = False
                    if not self.local.enabled:
                        self.local.enabled = True
                        await self.owner.send_negotiate(_TC.WILL, self.opcode)
                        await self.enable_local()
                        if self.opcode in self.owner.handshakes.local:
                            self.owner.handshakes.local.remove(self.opcode)
                            await self.owner.check_ready()
                else:
                    self.local.enabled = True
                    await self.owner.send_negotiate(_TC.WILL, self.opcode)
                    await self.enable_local()
                    if self.opcode in self.owner.handshakes.local:
                        self.owner.handshakes.local.remove(self.opcode)
                        await self.owner.check_ready()
            else:
                await self.owner.send_negotiate(_TC.DONT, self.opcode)

        elif cmd == _TC.WONT:
            if self.remote.enabled:
                await self.disable_remote()
                if self.remote.negotiating:
                    self.remote.negotiating = False
                    if self.opcode in self.owner.handshakes.remote:
                        self.owner.handshakes.remote.remove(self.opcode)
                    await self.owner.check_ready()

        elif cmd == _TC.DONT:
            if self.local.enabled:
                await self.disable_remote()
                if self.local.negotiating:
                    self.local.negotiating = False
                    if self.opcode in self.owner.handshakes.local:
                        self.owner.handshakes.local.remove(self.opcode)
                    await self.owner.check_ready()

    async def enable_local(self):
        pass

    async def disable_local(self):
        pass

    async def enable_remote(self):
        pass

    async def disable_remote(self):
        pass


class MCCP2Handler(TelnetOptionHandler):
    opcode = _TC.MCCP2
    support_local = True
    start_will = True
    hs_local = [opcode]

    async def enable_local(self):
        self.owner.capabilities.mccp2 = True
        await self.owner.send_subnegotiate(self.opcode, [])
        await self.owner.on_update()

    async def disable_local(self):
        self.owner.capabilities.mccp2 = False
        self.owner.out_compress = None
        await self.owner.on_update()


class TTYPEHandler(TelnetOptionHandler):
    opcode = _TC.TTYPE
    support_remote = True
    start_do = True
    hs_remote = [opcode]
    hs_special = [0, 1, 2]
    # terminal capabilities and their codes
    mtts = [
        (128, "proxy"),
        (64, "screen_reader"),
        (32, "osc_color_palette"),
        (16, "mouse_tracking"),
        (8, "xterm256"),
        (4, "utf8"),
        (2, "vt100"),
        (1, "ansi"),
    ]

    def __init__(self, owner):
        super().__init__(owner)
        self.stage = 0
        self.previous = None

    async def request(self):
        await self.owner.send_subnegotiate(self.opcode, [1])

    async def enable_remote(self):
        self.owner.capabilities.mtts = True
        await self.owner.on_update()
        await self.request()

    async def disable_remote(self):
        self.owner.capabilities.mtts = False
        await self.owner.on_update()

    async def subnegotiate(self, data):
        if data == self.previous:
            # we're not going to learn anything new from this client...
            for code in self.hs_special:
                if code in self.owner.handshakes.special:
                    self.owner.handshakes.special.remove(code)
            self.previous = None
            await self.owner.check_ready()

        if data[0] == 0:
            self.previous = data
            data = data[1:]
            data = data.decode(errors='ignore')
            if not data:
                return

            if self.stage == 0:
                await self.receive_stage_0(data)
                self.stage = 1
                await self.request()
            elif self.stage == 1:
                await self.receive_stage_1(data)
                self.stage = 2
            elif self.stage == 2:
                await self.receive_stage_2(data)
                self.stage = 3
            await self.owner.on_update()

    async def receive_stage_0(self, data):
        # Code adapted from Evennia! Credit where credit is due.

        # this is supposed to be the name of the client/terminal.
        # For clients not supporting the extended TTYPE
        # definition, subsequent calls will just repeat-return this.
        clientname = data.upper()

        if ' ' in clientname:
            clientname, version = clientname.split(' ', 1)
        else:
            version = 'UNKNOWN'
        self.owner.capabilities.client_name = clientname
        self.owner.capabilities.client_version = version

        # use name to identify support for xterm256. Many of these
        # only support after a certain version, but all support
        # it since at least 4 years. We assume recent client here for now.
        xterm256 = False
        if clientname.startswith("MUDLET"):
            # supports xterm256 stably since 1.1 (2010?)
            xterm256 = version >= "1.1"
            self.owner.capabilities.force_endline = False

        if clientname.startswith("TINTIN++"):
            self.owner.capabilities.force_endline = True

        if (
                clientname.startswith("XTERM")
                or clientname.endswith("-256COLOR")
                or clientname
                in (
                "ATLANTIS",  # > 0.9.9.0 (aug 2009)
                "CMUD",  # > 3.04 (mar 2009)
                "KILDCLIENT",  # > 2.2.0 (sep 2005)
                "MUDLET",  # > beta 15 (sep 2009)
                "MUSHCLIENT",  # > 4.02 (apr 2007)
                "PUTTY",  # > 0.58 (apr 2005)
                "BEIP",  # > 2.00.206 (late 2009) (BeipMu)
                "POTATO",  # > 2.00 (maybe earlier)
                "TINYFUGUE",  # > 4.x (maybe earlier)
        )
        ):
            xterm256 = True

        # all clients supporting TTYPE at all seem to support ANSI
        self.owner.capabilities.ansi = True
        self.owner.capabilities.xterm256 = xterm256

    async def receive_stage_1(self, term):
        # this is a term capabilities flag
        tupper = term.upper()
        # identify xterm256 based on flag
        xterm256 = (
                tupper.endswith("-256COLOR")
                or tupper.endswith("XTERM")  # Apple Terminal, old Tintin
                and not tupper.endswith("-COLOR")  # old Tintin, Putty
        )
        if xterm256:
            self.owner.capabilities.ansi = True
            self.owner.capabilities.xterm256 = xterm256
        self.owner.capabilities.terminal_type = term

    async def receive_stage_2(self, option):
        # the MTTS bitstring identifying term capabilities
        if option.startswith("MTTS"):
            option = option[4:].strip()
            if option.isdigit():
                # a number - determine the actual capabilities
                option = int(option)
                for k, v in {capability: True for bitval, capability in self.mtts if option & bitval > 0}:
                    setattr(self.owner.capabilities, k, v)
            else:
                # some clients send erroneous MTTS as a string. Add directly.
                self.owner.capabilities.mtts = True
        self.owner.capabilities.ttype = True


class MNEShandler(TelnetOptionHandler):
    """
    Not ready. do not enable.
    """
    opcode = _TC.MNES
    start_do = True
    support_remote = True
    hs_remote = [opcode]


class MCCP3Handler(TelnetOptionHandler):
    """
    Note: Disabled because I can't get this working in tintin++
    It works, but not in conjunction with MCCP2.
    """
    opcode = _TC.MCCP3
    support_local = True
    start_will = True
    hs_local = [opcode]

    async def subnegotiate(self, data):
        if not self.owner.in_compress:
            self.owner.in_compress = zlib.decompressobj()
            if self.owner.inbox:
                remaining = self.owner.in_compress.decompress(self.owner.inbox)
                self.owner.inbox.clear()
                self.owner.inbox.extend(remaining)


class NAWSHandler(TelnetOptionHandler):
    opcode = _TC.NAWS
    support_remote = True
    start_do = True

    async def enable_remote(self):
        self.owner.capabilities.naws = True
        await self.owner.on_update()

    async def subnegotiate(self, data):
        if len(data) >= 4:
            # NAWS is negotiated with 16bit words
            new_width = int.from_bytes(data[0:2], byteorder="big", signed=False)
            new_height = int.from_bytes(data[2:2], byteorder="big", signed=False)
            changed = False
            if new_width != self.owner.capabilities.width or new_height != self.owner.capabilities.height:
                changed = True
            self.owner.capabilities.width = new_width
            self.owner.capabilities.height = new_height
            if changed:
                await self.owner.on_update()


class SGAHandler(TelnetOptionHandler):
    opcode = _TC.SGA
    start_will = True
    support_local = True

    async def enable_local(self):
        self.owner.capabilities.suppress_ga = True
        await self.owner.on_update()

    async def disable_local(self):
        self.owner.capabilities.suppress_ga = False
        await self.owner.on_update()


class LinemodeHandler(TelnetOptionHandler):
    opcode = _TC.LINEMODE
    start_do = True
    support_remote = True

    async def enable_remote(self):
        self.owner.capabilities.linemode = True
        await self.owner.on_update()

    async def disable_remote(self):
        self.owner.capabilities.linemode = False
        await self.owner.on_update()


class MSSPHandler(TelnetOptionHandler):
    opcode = _TC.MSSP
    start_will = True
    support_local = True

    def __init__(self, owner):
        super().__init__(owner)
        owner.mssp = self

    async def enable_local(self):
        self.owner.capabilities.mssp = True
        await self.owner.on_update()

    async def disable_local(self):
        self.owner.capabilities.mssp = False
        await self.owner.on_update()

    async def send(self, data: Dict[str, str]):
        out = bytearray([_TC.IAC, _TC.SB, self.opcode])
        for k, v in data.items():
            out += 1
            out += bytes(k)
            out += 2
            out += bytes(v)
        out.extend([_TC.IAC, _TC.SE])
        await self.owner.outbox.put(TelnetOutMessage(out))


class TelnetMudConnection(MudConnection):
    handler_classes = [MCCP2Handler, TTYPEHandler, NAWSHandler, SGAHandler, LinemodeHandler, MSSPHandler]

    def __init__(self, listener, reader, writer):
        super().__init__(listener)
        self.reader = reader
        self.writer = writer
        self.inbox = bytearray()
        self.cmdbuff = bytearray()
        self.outbox = asyncio.Queue()
        self.handlers = {hc.opcode: hc(self) for hc in self.handler_classes}
        self.out_compressor = None
        self.in_compress = None
        self.handshakes = TelnetHandshakeHolder(self)
        self.host, self.host_port = self.writer.get_extra_info('peername')

        for k, v in self.handlers.items():
            if v.start_will:
                msg = TelnetOutMessage(bytearray([_TC.IAC, _TC.WILL, k]))
                self.outbox.put_nowait(msg)
                v.local.negotiating = True
                v.local.asked = True

            if v.start_do:
                msg = TelnetOutMessage(bytearray([_TC.IAC, _TC.DO, k]))
                self.outbox.put_nowait(msg)
                v.remote.negotiating = True
                v.remote.asked = True

            if v.hs_local:
                self.handshakes.local.update(v.hs_local)
            if v.hs_remote:
                self.handshakes.remote.update(v.hs_remote)
            if v.hs_special:
                self.handshakes.special.update(v.hs_special)

    async def check_ready(self):
        if self.ready:
            return
        if self.handshakes.has_remaining():
            return
        await self.on_ready()

    async def run_timer(self):
        await asyncio.sleep(0.3)
        await self.on_ready()

    async def run(self):
        await self.listener.manager.announce_conn(self)
        await asyncio.gather(self.read(), self.write(), self.keepalive(), self.run_timer())

    async def keepalive(self):
        while self.running:
            if self.capabilities.keepalive:
                msg = TelnetOutMessage(bytearray([_TC.IAC, _TC.NOP]))
                await self.outbox.put(msg)
            await asyncio.sleep(30)

    async def read(self):
        while self.running:
            data = await self.reader.read(4096)
            if len(data):
                if self.in_compress:
                    data = self.in_compress.decompress(data)
                self.inbox += data
                await self.read_telnet()
            else:
                self.running = False
                await self.on_disconnect()

    async def write(self):
        while self.running:
            msg = await self.outbox.get()
            data = msg.data
            if data:
                if self.out_compressor:
                    data = self.out_compressor.compress(data) + self.out_compressor.flush(zlib.Z_SYNC_FLUSH)
                self.writer.write(data)
            if msg.enable_compress2 and not self.out_compressor:
                self.out_compressor = zlib.compressobj(9)
            if msg.close and self.writer.can_write_eof():
                self.running = False
                if self.out_compressor:
                    self.writer.write(self.out_compressor.flush(zlib.Z_FINISH))
                self.writer.write_eof()

    async def close(self):
        msg = TelnetOutMessage(bytearray())
        msg.close = True
        await self.outbox.put(msg)

    async def read_telnet(self):
        while len(self.inbox) > 0:
            if self.inbox[0] == _TC.IAC:
                if len(self.inbox) < 2:
                    # not enough bytes available to do anything.
                    return
                else:
                    if self.inbox[1] == _TC.IAC:
                        del self.inbox[0:2]
                        self.cmdbuff.append(_TC.IAC)
                        await self.read_command()
                        continue
                    elif self.inbox[1] in NEGOTIATORS:
                        if len(self.inbox) > 2:
                            cmd, option = self.inbox[1], self.inbox[2]
                            del self.inbox[0:3]
                            await self.negotiate(cmd, option)
                            continue
                        else:
                            # it's a negotiation, but we need more.
                            return
                    elif self.inbox[1] == _TC.SB:
                        if len(self.inbox) >= 5:
                            match = bytearray()
                            match.append(_TC.IAC)
                            match.append(_TC.SE)
                            idx = self.inbox.find(match)
                            if idx == -1:
                                return
                            # hooray, idx is the beginning of our ending IAC SE!
                            option = self.inbox[2]
                            data = self.inbox[3:idx]
                            del self.inbox[:idx + 2]
                            await self.subnegotiate(option, data)
                            continue
                        else:
                            # it's a subnegotiate, but we need more.
                            return
                    else:
                        cmd = self.inbox[1]
                        del self.inbox[0:2]
                        await self.handle_cmd(cmd)
                        continue
            else:
                # we are dealing with 'just data!'
                idx = self.inbox.find(_TC.IAC)
                if idx == -1:
                    # no idx. consume entire remaining buffer.
                    self.cmdbuff.extend(self.inbox)
                    self.inbox.clear()
                    await self.read_command()
                    continue
                else:
                    # There is an IAC ahead - consume up to it, and loop.
                    self.cmdbuff.extend(self.inbox[:idx])
                    del self.inbox[:idx]
                    await self.read_command()
                    continue

    async def handle_command(self, cmd):
        if cmd == _TC.NOP:
            return

    async def read_command(self):
        while True:
            idx = self.cmdbuff.find(_TC.LF)
            if idx == -1:
                break
            found = self.cmdbuff[:idx]
            if found.endswith(b'\r'):
                del found[-1]
            if found and callable(self.on_command_cb):
                if inspect.iscoroutinefunction(self.on_command_cb):
                    await self.on_command_cb(self, found)
                else:
                    self.on_command_cb(self, found)
            del self.cmdbuff[:idx + 1]

    async def negotiate(self, cmd, option):
        if (handler := self.handlers.get(option, None)):
            await handler.negotiate(cmd)
        elif (response := NEG_OPPOSITES.get(cmd, None)):
            await self.send_negotiate(response, option)

    async def subnegotiate(self, option, data):
        if (handler := self.handlers.get(option, None)):
            await handler.subnegotiate(data)

    async def send_negotiate(self, cmd, option):
        msg = TelnetOutMessage(bytearray([_TC.IAC, cmd, option]))
        await self.outbox.put(msg)

    async def send_subnegotiate(self, cmd, data):
        out = bytearray([_TC.IAC, _TC.SB, cmd])
        out.extend(data)
        out.extend([_TC.IAC, _TC.SE])
        msg = TelnetOutMessage(out)
        if cmd == _TC.MCCP2:
            msg.enable_compress2 = True
        await self.outbox.put(msg)

    async def send_bytes(self, data):
        if self.capabilities.suppress_ga:
            msg = TelnetOutMessage(data)
        else:
            msg = TelnetOutMessage(data + _TC.GA)
        await self.outbox.put(msg)
