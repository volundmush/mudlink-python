from mudlink.mudlink import MudLinkManager
import asyncio
import uvloop


async def got_a_conn(conn):
    print(f"GOT A {conn.name} - {conn}")
    print(conn.capabilities.__dict__)


async def main():
    manager = MudLinkManager()
    manager.register_listener("telnet", "any", 7999, "telnet")
    manager.on_connect_cb = got_a_conn
    manager.start()
    await manager.run()

if __name__ == "__main__":
    uvloop.install()
    asyncio.run(main(), debug=True)
