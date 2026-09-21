"""CLI-owned server tests: fake Uvicorn, mock dial, no real I/O."""

import asyncio

import pytest

import caller


class FakeServer:
    def __init__(self, config):
        self.config = config
        self.started = False
        self.should_exit = False
        self.fail = None

    async def serve(self):
        if self.fail is not None:
            raise self.fail
        self.started = True
        while not self.should_exit:
            await asyncio.sleep(0.01)


@pytest.fixture
def fake_uvicorn(monkeypatch):
    servers = []
    configs = []

    def make_config(app, **kwargs):
        configs.append(kwargs)
        return {"app": app, **kwargs}

    def make_server(config):
        server = FakeServer(config)
        servers.append(server)
        return server

    monkeypatch.setattr(caller.uvicorn, "Config", make_config)
    monkeypatch.setattr(caller.uvicorn, "Server", make_server)
    return servers, configs


class FakeCaller:
    def __init__(self, exit_code=0, outcome="completed"):
        self.starts = 0
        self.closes = 0
        self.done = asyncio.Event()
        self.exit_code = exit_code
        self.outcome = outcome
        self.saw_started = None

    async def start(self):
        self.starts += 1
        self.done.set()

    async def close(self):
        self.closes += 1


def _install_caller(monkeypatch, app_name, fake):
    import webhooks

    app = webhooks.public_app if app_name == "public" else webhooks.client_app
    monkeypatch.setattr(app.state, "caller", fake, raising=False)
    return app


def test_run_call_dials_once_after_readiness(fake_uvicorn, monkeypatch, capsys):
    servers, configs = fake_uvicorn
    fake = FakeCaller()

    orig_start = fake.start

    async def start():
        fake.saw_started = servers[0].started
        await orig_start()

    fake.start = start
    app = _install_caller(monkeypatch, "client", fake)
    code = asyncio.run(caller.run_call("client", ".env"))
    assert code == 0
    assert fake.starts == 1
    assert fake.saw_started is True
    assert servers[0].should_exit is True
    assert fake.closes >= 1
    assert configs[0]["port"] == 8011
    assert configs[0]["host"] == "127.0.0.1"
    assert configs[0]["workers"] == 1
    assert configs[0]["access_log"] is False
    assert configs[0]["env_file"] == ".env"
    assert getattr(app.state, "caller_enabled", False) is False
    out, err = capsys.readouterr()
    assert out == ""
    assert err.strip() != ""


def test_public_port_and_failure_exit(fake_uvicorn, monkeypatch, capsys):
    _, configs = fake_uvicorn
    fake = FakeCaller(exit_code=1, outcome="stage_timeout")
    _install_caller(monkeypatch, "public", fake)
    code = asyncio.run(caller.run_call("public", ".env"))
    assert code == 1
    assert configs[0]["port"] == 8010
    out, err = capsys.readouterr()
    assert out == ""
    assert "stage_timeout" in err


def test_startup_failure_dials_zero_times(fake_uvicorn, monkeypatch, capsys):
    import webhooks

    servers, _ = fake_uvicorn
    fake = FakeCaller()
    calls = []

    async def start():
        calls.append(1)
        await FakeCaller.start(fake)

    fake.start = start
    _install_caller(monkeypatch, "client", fake)

    orig_server = caller.uvicorn.Server

    def make_server(config):
        server = FakeServer(config)
        server.fail = SystemExit(1)
        servers.append(server)
        return server

    monkeypatch.setattr(caller.uvicorn, "Server", make_server)
    assert webhooks.client_app is not None and orig_server is not None
    code = asyncio.run(caller.run_call("client", ".env"))
    assert code != 0
    assert calls == []
    out, _ = capsys.readouterr()
    assert out == ""


def test_constructor_failure_clears_flag_without_dial(
    fake_uvicorn, monkeypatch, capsys
):
    import webhooks

    servers, _ = fake_uvicorn
    fake = FakeCaller()
    _install_caller(monkeypatch, "client", fake)

    def boom_config(app, **kwargs):
        raise RuntimeError("config exploded")

    monkeypatch.setattr(caller.uvicorn, "Config", boom_config)
    code = asyncio.run(caller.run_call("client", ".env"))
    assert code == 1
    assert fake.starts == 0
    assert servers == []
    assert getattr(webhooks.client_app.state, "caller_enabled", False) is False
    out, err = capsys.readouterr()
    assert out == ""
    lines = err.strip().splitlines()
    assert len(lines) == 1
    assert "server_startup_failed" in lines[0]


def test_cancellation_runs_cleanup(fake_uvicorn, monkeypatch):
    servers, _ = fake_uvicorn

    class HangingCaller(FakeCaller):
        async def start(self):
            self.starts += 1
            # never sets done; cancellation must still clean up

    fake = HangingCaller()
    _install_caller(monkeypatch, "client", fake)

    async def exercise():
        task = asyncio.create_task(caller.run_call("client", ".env"))
        for _ in range(200):
            if fake.starts:
                break
            await asyncio.sleep(0.01)
        assert fake.starts == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert fake.closes >= 1
        assert servers[0].should_exit is True

    asyncio.run(exercise())


def test_cli_args():
    parser = caller.build_parser()
    args = parser.parse_args([])
    assert args.app == "public"
    assert args.env_file == ".env"
    args = parser.parse_args(["--app", "client", "--env-file", "custom.env"])
    assert args.app == "client"
    assert args.env_file == "custom.env"
    with pytest.raises(SystemExit):
        parser.parse_args(["--app", "bogus"])
    flags = {action.dest for action in parser._actions}
    assert flags == {"help", "env_file", "app"}


def test_imports_never_dial():
    assert caller.__name__ == "caller"
