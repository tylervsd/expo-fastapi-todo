"""Local one-call CLI that owns its webhook server."""

import argparse
import asyncio
import sys
from contextlib import suppress

import uvicorn

import webhooks

_PORTS = {"public": 8010, "client": 8011}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Place one automated IVR test call.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--app", choices=("public", "client"), default="public")
    return parser


async def _wait_ready(server: uvicorn.Server, task: asyncio.Task) -> bool:
    # Server startup polling only; never prompt navigation.
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 10
    while not server.started:
        if task.done():
            return False
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(0.05)
    return not task.done()


async def _cleanup(caller) -> None:
    if caller is not None:
        with suppress(Exception):
            await caller.close()


async def run_call(app_name: str, env_file: str) -> int:
    app = webhooks.public_app if app_name == "public" else webhooks.client_app
    server = None
    server_task = None
    caller = None
    outcome = "server_startup_failed"
    exit_code = 1
    try:
        app.state.caller_enabled = True
        try:
            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=_PORTS[app_name],
                env_file=env_file,
                access_log=False,
                workers=1,
            )
            server = uvicorn.Server(config)
        except Exception:  # noqa: BLE001 — no server exists; keep startup-failed outcome
            return 1
        serve_error: BaseException | None = None

        async def _serve() -> None:
            # Never let BaseExceptions (e.g. early SystemExit) live on the task:
            # awaiting such a task re-raises through the loop instead of the
            # awaiter, so capture the error and exit normally.
            nonlocal serve_error
            try:
                await server.serve()
            except BaseException as error:  # noqa: BLE001 — startup failure signal
                serve_error = error

        server_task = asyncio.create_task(_serve())
        try:
            if not await _wait_ready(server, server_task):
                return 1
            caller = getattr(app.state, "caller", None)
            if caller is None:
                outcome = "caller_unavailable"
                return 1
            try:
                await caller.start()
            except Exception:  # noqa: BLE001 — start failure is a sanitized outcome, never a URL leak
                outcome = "dial_reservation_failed"
                return 1
            waiter = asyncio.create_task(caller.done.wait())
            try:
                await asyncio.wait(
                    {waiter, server_task}, return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                if not waiter.done():
                    waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)
            if server_task.done() and not caller.done.is_set():
                outcome = "server_stopped"
                return 1
            await _cleanup(caller)
            outcome = caller.outcome or "unknown"
            exit_code = caller.exit_code if caller.exit_code is not None else 1
            return exit_code
        except Exception:  # noqa: BLE001 — sanitized outcome only; raw HTTP text may carry call-control URLs
            outcome = "internal_error"
            return 1
    except asyncio.CancelledError:
        with suppress(Exception):
            await asyncio.shield(_cleanup(caller))
        raise
    finally:
        if server is not None:
            server.should_exit = True
        if server_task is not None and not server_task.done():
            with suppress(Exception):
                await asyncio.wait_for(asyncio.shield(server_task), timeout=10)
        with suppress(AttributeError, KeyError):
            del app.state.caller_enabled
        # Concise stderr diagnostic; stdout stays empty (Lesson 4 owns JSON).
        print(f"ivr caller {app_name}: {outcome} (exit {exit_code})", file=sys.stderr)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(run_call(args.app, args.env_file))


if __name__ == "__main__":
    raise SystemExit(main())
