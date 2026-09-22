"""Local one-call CLI that owns its webhook server."""

import argparse
import asyncio
import json
import sys
from contextlib import suppress

import uvicorn

import webhooks
from client import error_result

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
        try:
            async with asyncio.timeout(20):
                await caller.close()
        except Exception:  # noqa: BLE001 — cleanup cannot overwrite the terminal result
            print("ivr caller: cleanup_failed", file=sys.stderr)


async def run_call(app_name: str, env_file: str) -> int:
    app = webhooks.public_app if app_name == "public" else webhooks.client_app
    server = None
    server_task = None
    caller = None
    outcome = "server_startup_failed"
    exit_code = 1
    payload = None
    stage = "startup"
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
            stage = "dialing"
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
            outcome = caller.outcome or "unknown"
            payload = caller.result or error_result("internal_error", stage)
            exit_code = 0 if payload["status"] == "success" else 1
            return exit_code
        except Exception:  # noqa: BLE001 — sanitized outcome only; raw HTTP text may carry call-control URLs
            outcome = "internal_error"
            return 1
    except asyncio.CancelledError:
        outcome = "interrupted"
        exit_code = 130
        flow = getattr(caller, "flow", None)
        payload = getattr(caller, "result", None) or getattr(flow, "result", None)
        raise
    finally:
        flow = getattr(caller, "flow", None)
        if payload is None:
            payload = error_result(
                outcome,
                getattr(flow, "failure_stage", None) or getattr(flow, "stage", stage),
            )
        try:
            await asyncio.shield(_cleanup(caller))
            if server is not None:
                server.should_exit = True
            if server_task is not None and not server_task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(server_task), timeout=10)
                except TimeoutError:
                    server_task.cancel()
                    await asyncio.gather(server_task, return_exceptions=True)
        finally:
            with suppress(AttributeError, KeyError):
                del app.state.caller_enabled
            print(
                f"ivr caller {app_name}: {outcome} (exit {exit_code})", file=sys.stderr
            )
            print(json.dumps(payload))


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(run_call(args.app, args.env_file))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
