import asyncio
import json
from types import SimpleNamespace

from cloud_runner import Control


class Writer:
    def __init__(self):
        self.data = b""

    def write(self, data):
        self.data += data

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


def test_control_single_start_and_status():
    async def exercise():
        caller = SimpleNamespace(
            _started=False,
            done=asyncio.Event(),
            flow=None,
            result=None,
            outcome=None,
            exit_code=None,
        )
        calls = []

        async def start():
            calls.append(1)
            caller._started = True

        caller.start = start
        control = Control(caller, lambda: True)

        async def request(data):
            reader, writer = asyncio.StreamReader(), Writer()
            reader.feed_data(data)
            reader.feed_eof()
            await control.handle(reader, writer)
            return json.loads(writer.data)

        assert (await request(b"status\n"))["started"] is False
        assert (await request(b"result\n"))["code"] == "result_not_ready"
        assert calls == []
        results = await asyncio.gather(request(b"start\n"), request(b"start\n"))
        assert {r["status"] for r in results} == {"started", "busy"}
        assert len(calls) == 1
        caller.result = {"status": "success", "value": "0.00", "currency": "USD"}
        assert (await request(b"result\n"))["code"] == "result_not_ready"
        caller.done.set()
        assert (await request(b"result\n")) == caller.result
        assert (await request(b"result\n")) == caller.result
        assert (await request(b"status\n"))["result"] == caller.result
        assert len(calls) == 1
        assert (await request(b"start\n"))["status"] == "restart_required"
        for invalid in (b"bad\n", b"start", b"x" * 65 + b"\n"):
            assert (await request(invalid))["status"] == "invalid_request"
        control.ready = lambda: False
        assert (await request(b"start\n"))["status"] == "not_ready"
        assert len(calls) == 1

    asyncio.run(exercise())


def test_server_never_dials_and_survives_completion(monkeypatch, tmp_path):
    from contextlib import asynccontextmanager

    from fastapi import FastAPI

    import cloud_runner

    monkeypatch.setattr(cloud_runner.webhooks, "public_app", FastAPI())

    async def exercise():
        caller = SimpleNamespace(
            _started=False,
            done=asyncio.Event(),
            flow=None,
            result=None,
            outcome=None,
            exit_code=None,
        )

        async def start():
            raise AssertionError("Server startup must not dial")

        caller.start = start

        @asynccontextmanager
        async def lifespan(app):
            app.state.caller = caller
            yield

        monkeypatch.setattr(
            cloud_runner.webhooks.public_app.router, "lifespan_context", lifespan
        )
        socket = tmp_path / "control.sock"
        monkeypatch.setattr(cloud_runner, "SOCKET", socket)

        class Listener:
            def close(self):
                pass

            async def wait_closed(self):
                pass

        async def listen(handler, *, path, limit):
            assert limit == 64
            socket.touch()
            return Listener()

        monkeypatch.setattr(cloud_runner.asyncio, "start_unix_server", listen)

        class Server:
            def __init__(self, config):
                self.config = config
                self.started = False
                self.should_exit = False

            async def serve(self):
                app = self.config.app
                async with app.router.lifespan_context(app):
                    self.started = True
                    assert socket.stat().st_mode & 0o777 == 0o600
                    caller.done.set()
                    await asyncio.sleep(0)
                    assert socket.exists()
                    assert not caller._started

        monkeypatch.setattr(cloud_runner.uvicorn, "Server", Server)
        await cloud_runner.serve()
        assert not socket.exists()

    asyncio.run(exercise())


def test_result_request_output_and_exit(monkeypatch, capsys):
    import cloud_runner

    async def exercise():
        for payload, expected in [
            ({"status": "success", "value": "0.00", "currency": "USD"}, 0),
            ({"status": "error", "code": "result_unrecognized", "stage": "result"}, 1),
            ({"status": "error", "code": "result_not_ready", "stage": "startup"}, 1),
        ]:
            writer = Writer()

            async def connect(*args, payload=payload, writer=writer, **kwargs):
                reader = asyncio.StreamReader()
                reader.feed_data(json.dumps(payload).encode() + b"\n")
                reader.feed_eof()
                return reader, writer

            monkeypatch.setattr(cloud_runner.asyncio, "open_unix_connection", connect)
            assert await cloud_runner.request("result") == expected
            out, _ = capsys.readouterr()
            assert len(out.splitlines()) == 1
            assert json.loads(out) == payload
            assert writer.data == b"result\n"

    asyncio.run(exercise())
