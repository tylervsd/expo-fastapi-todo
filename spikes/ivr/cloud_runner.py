"""Persistent webhook server with SSH-only, one-call control."""

import argparse
import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn

import webhooks

SOCKET = Path("/run/ivr/control.sock")


class Control:
    def __init__(self, caller, ready):
        self.caller, self.ready = caller, ready
        self.lock = asyncio.Lock()
        self.active = set()

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        admitted = len(self.active) < 4
        if admitted:
            self.active.add(task)
        try:
            if not admitted:
                response = {"status": "busy"}
            else:
                try:
                    async with asyncio.timeout(2):
                        data = await reader.readuntil(b"\n")
                    if len(data) > 64 or data not in (
                        b"start\n",
                        b"status\n",
                        b"result\n",
                    ):
                        raise ValueError
                except (
                    ValueError,
                    TimeoutError,
                    asyncio.IncompleteReadError,
                    asyncio.LimitOverrunError,
                ):
                    response = {"status": "invalid_request"}
                else:
                    async with self.lock:
                        if not self.ready():
                            response = {"status": "not_ready"}
                        elif data == b"result\n":
                            response = (
                                dict(self.caller.result)
                                if self.caller.done.is_set()
                                and self.caller.result is not None
                                else {
                                    "status": "error",
                                    "code": "result_not_ready",
                                    "stage": "startup",
                                }
                            )
                        elif data == b"status\n":
                            flow = self.caller.flow
                            response = {
                                "started": self.caller._started,
                                "done": self.caller.done.is_set(),
                                "stage": flow.stage if flow else "idle",
                                "outcome": self.caller.outcome,
                                "exit_code": self.caller.exit_code,
                                "result": self.caller.result
                                if self.caller.done.is_set()
                                else None,
                            }
                        elif self.caller._started:
                            response = {
                                "status": "restart_required"
                                if self.caller.done.is_set()
                                else "busy"
                            }
                        else:
                            await self.caller.start()
                            response = {"status": "started"}
            writer.write(json.dumps(response).encode() + b"\n")
            async with asyncio.timeout(2):
                await writer.drain()
        except ConnectionError, TimeoutError:
            pass  # A disconnected SSH client never cancels the call.
        finally:
            self.active.discard(task)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass


async def serve():
    app = webhooks.public_app
    app.state.caller_enabled = True
    previous = app.router.lifespan_context
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=8010, access_log=False)
    )

    @asynccontextmanager
    async def lifespan(app):
        async with previous(app):
            # Never unlink a pre-existing socket: systemd owns the runtime directory.
            if SOCKET.exists() or SOCKET.is_symlink():
                raise RuntimeError("Control socket already exists")
            control = Control(
                app.state.caller, lambda: server.started and not server.should_exit
            )
            listener = await asyncio.start_unix_server(
                control.handle, path=str(SOCKET), limit=64
            )
            os.chmod(SOCKET, 0o600)
            try:
                yield
            finally:
                listener.close()
                await listener.wait_closed()
                for task in list(control.active):
                    task.cancel()
                await asyncio.gather(*list(control.active), return_exceptions=True)
                SOCKET.unlink(missing_ok=True)

    app.router.lifespan_context = lifespan
    try:
        await server.serve()
    finally:
        app.router.lifespan_context = previous


async def request(command):
    async with asyncio.timeout(5):
        reader, writer = await asyncio.open_unix_connection(str(SOCKET), limit=1024)
        try:
            writer.write(command.encode() + b"\n")
            await writer.drain()
            result = json.loads(await reader.readline())
            print(json.dumps(result))
            return (
                0
                if command == "status"
                or result.get("status")
                == ("success" if command == "result" else "started")
                else 1
            )
        finally:
            writer.close()
            await writer.wait_closed()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("serve", "start", "status", "result"))
    command = parser.parse_args().command
    try:
        return asyncio.run(serve() if command == "serve" else request(command))
    except OSError, TimeoutError, ValueError:
        parser.exit(1, "IVR control unavailable; inspect service status.\n")


if __name__ == "__main__":
    raise SystemExit(main())
