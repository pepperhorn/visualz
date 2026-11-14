"""REST /api and /ws. WS receives {type:patch, patch:{...}} and emits full state.

State messages: {type:state,state:{...}}. Telemetry is a separate volatile message
{type:telemetry,audio:{...},stage:{...}} at 10 Hz; it is never persisted.
Collections are /api/{scenes,overlays,picture_sets}; POST creates, PUT replaces,
PATCH merges, DELETE removes. POST /api/overlays/{id}/live takes a slide live;
/api/overlays/{next,prev,clear,order} manages the slide list. Scene /{id}/live
recalls it. POST /api/assets?kind=image|logo|clip|font accepts a multipart file.
Overlay /{id}/export returns a ZIP; POST /api/overlays/import imports ZIP bytes.
Worker API: POST /api/stage/command {target,name,args}; GET /api/stage/status;
GET /api/stage/image/<name>. WS {type:command,target,name,args} uses the same
queue. See visualz.state.runtime for the initial command/status contract.
"""

import asyncio
import json
import logging
import sysconfig
import threading
import shutil
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from aiohttp import WSMsgType, web

from visualz import overlay
from visualz.media import MAX_UPLOAD, ingest
from visualz.media.archive import (
    checked_path,
    references as asset_refs,
    import_archive,
    loop_manifest,
)
from visualz.schema import SCHEMAS, validate
from visualz.schema.profiles import media_options, archive_limit
from visualz.state import COLLECTIONS, merge
from visualz.state.runtime import CommandQueueFull


MAX_COMMAND_BODY = 64 * 1024


@web.middleware
async def errors(request, handler):
    if request.method == "POST" and request.path == "/api/stage/command":
        # Share the bounded request/cache with both the handler and error replies.
        request = request.clone(client_max_size=MAX_COMMAND_BODY)
    try:
        return await handler(request)
    except CommandQueueFull as exc:
        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = {}
        return web.json_response(
            {"error": str(exc), "id": body.get("id") if isinstance(body, dict) else None},
            status=503,
            headers={"Retry-After": "1"},
        )
    except FileNotFoundError as exc:
        raise web.HTTPNotFound(text="Asset file not found") from exc
    except (ValueError, KeyError, TypeError, BadZipFile) as exc:
        return web.json_response({"error": str(exc)}, status=400)


def create_app(store, telemetry=None, web_dir=None):
    """Build app; optional telemetry() returns JSON-safe audio/stage status."""
    app = web.Application(client_max_size=MAX_UPLOAD, middlewares=[errors])
    clients = set()
    telemetry = telemetry or store.runtime.status
    root = store.data_dir

    async def send(ws, message):
        try:
            await asyncio.wait_for(
                ws.send_json(
                    store.runtime.coerce(message, "send"),
                    dumps=lambda value: json.dumps(value, allow_nan=False),
                ),
                0.5,
            )
        except (ConnectionError, RuntimeError, asyncio.TimeoutError):
            clients.discard(ws)
            asyncio.create_task(ws.close())
        except Exception:
            logging.exception("Failed to send client message; keeping stream alive")

    async def broadcast(message):
        await asyncio.gather(*(send(ws, message) for ws in tuple(clients)))

    async def lifecycle(app):
        loop = asyncio.get_running_loop()
        event = asyncio.Event()
        pending = [None]

        def changed(state):
            pending[0] = state
            loop.call_soon_threadsafe(event.set)

        unsubscribe = store.subscribe(changed)

        async def states():
            while True:
                await event.wait()
                event.clear()
                try:
                    await broadcast({"type": "state", "state": pending[0]})
                except Exception:
                    logging.exception("State broadcast failed; continuing")

        async def meters():
            while True:
                await asyncio.sleep(0.1)
                try:
                    await broadcast(
                        {"type": "telemetry", **store.runtime.coerce(telemetry(), "telemetry")}
                    )
                except Exception:
                    logging.exception("Telemetry tick failed; continuing")

        async def supervise(name, factory):
            while True:
                child = asyncio.create_task(factory())
                try:
                    await child
                    logging.error("%s task exited; restarting", name)
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        child.cancel()
                        await asyncio.gather(child, return_exceptions=True)
                        raise
                    logging.warning("%s task cancelled unexpectedly; restarting", name)
                except Exception:
                    logging.exception("%s task failed; restarting", name)
                await asyncio.sleep(0.01)

        tasks = [
            asyncio.create_task(supervise("states", states)),
            asyncio.create_task(supervise("telemetry", meters)),
        ]
        yield
        unsubscribe()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(ws.close() for ws in tuple(clients)))

    app.cleanup_ctx.append(lifecycle)

    async def state(request):
        if request.method == "PATCH":
            store.patch(await request.json())
        return web.json_response(store.get())

    async def section(request):
        name = request.match_info["section"]
        if name not in ("settings", "now_playing"):
            raise web.HTTPNotFound()
        if request.method == "PATCH":
            store.patch({name: await request.json()})
        return web.json_response(store.get()[name])

    async def collection(request):
        name = request.match_info["collection"]
        if name not in COLLECTIONS:
            raise web.HTTPNotFound()
        if request.method == "POST":
            value = validate(COLLECTIONS[name], await request.json())

            def change(state):
                if value["id"] in state[name]:
                    raise ValueError("ID already exists")
                state[name][value["id"]] = value

            store.transaction(change)
            return web.json_response(value, status=201)
        return web.json_response(list(store.get()[name].values()))

    async def item(request):
        name, key = request.match_info["collection"], request.match_info["id"]
        if name not in COLLECTIONS or key not in store.get()[name]:
            raise web.HTTPNotFound()
        body = await request.json() if request.method in ("PUT", "PATCH") else None

        def change(state):
            if request.method == "DELETE":
                if name == "assets":
                    path = state[name][key]["path"]
                    if path in asset_refs({k: v for k, v in state.items() if k != "assets"}):
                        raise ValueError("Asset is in use; remove its references before deleting")
                if name == "picture_sets":
                    if state["settings"]["picture_set"] == key:
                        state["settings"]["picture_set"] = None
                    for scene in state["scenes"].values():
                        if scene.get("picture_set") == key:
                            scene["picture_set"] = None
                del state[name][key]
                for field in ("active_overlay", "active_scene"):
                    if (
                        state[field] == key
                        and name == {"active_overlay": "overlays", "active_scene": "scenes"}[field]
                    ):
                        state[field] = None
            elif request.method == "PUT":
                state[name][key] = body
            elif request.method == "PATCH":
                merge(state[name][key], body)

        if request.method != "GET":
            store.transaction(change)
            if request.method == "DELETE" and name == "assets":
                await asyncio.to_thread(shutil.rmtree, root / "assets" / key, True)
        return web.json_response(store.get()[name].get(key))

    async def live(request):
        name, key = request.match_info["collection"], request.match_info["id"]
        if name not in ("scenes", "overlays") or key not in store.get()[name]:
            raise web.HTTPNotFound()

        def change(state):
            state["active_overlay" if name == "overlays" else "active_scene"] = key
            if name == "scenes":
                scene = state[name][key]
                for field in (
                    "mode",
                    "modes",
                    "look",
                    "picture_set",
                    "source_asset",
                ):
                    if field in scene:
                        if field == "modes":
                            state["settings"]["modes"].update(scene[field])
                        else:
                            state["settings"][field] = scene[field]

        return web.json_response(store.transaction(change))

    async def slides(request):
        action = request.match_info["action"]
        body = await request.json() if action == "order" else None

        def change(state):
            ordered = sorted(state["overlays"], key=lambda k: (state["overlays"][k]["order"], k))
            if action == "order":
                if (
                    not isinstance(body, list)
                    or len(body) != len(ordered)
                    or set(body) != set(ordered)
                ):
                    raise ValueError("Order must contain every overlay ID exactly once")
                for n, key in enumerate(body):
                    state["overlays"][key]["order"] = n
            elif action == "clear" or not ordered:
                state["active_overlay"] = None
            else:
                current = state["active_overlay"]
                index = (
                    ordered.index(current)
                    if current in ordered
                    else (-1 if action == "next" else 0)
                )
                state["active_overlay"] = ordered[
                    (index + (1 if action == "next" else -1)) % len(ordered)
                ]

        return web.json_response(store.transaction(change))

    async def blackout(request):
        body = await request.json()
        return web.json_response(store.patch({"settings": {"blackout": body}}))

    async def websocket(request):
        ws = web.WebSocketResponse(max_msg_size=1024 * 1024, heartbeat=20)
        await ws.prepare(request)
        clients.add(ws)
        try:
            await ws.send_json({"type": "state", "state": store.get()})
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    body = None
                    try:
                        body = json.loads(msg.data)
                        if body.get("type") == "command":
                            loop = asyncio.get_running_loop()

                            def result_ready(result):
                                loop.call_soon_threadsafe(
                                    lambda: asyncio.create_task(
                                        send(ws, {"type": "command_result", **result})
                                    )
                                )

                            ack = store.runtime.enqueue_command(
                                {k: v for k, v in body.items() if k != "type"}, result_ready
                            )
                            await send(ws, {"type": "command", **ack})
                        elif body.get("type") == "patch":
                            store.patch(body["patch"])
                        else:
                            raise ValueError("Expected patch or command message")
                    except CommandQueueFull as exc:
                        await send(
                            ws,
                            {
                                "type": "error",
                                "error": str(exc),
                                "status": 503,
                                "retry_after": 1,
                                "id": body.get("id") if isinstance(body, dict) else None,
                            },
                        )
                    except (ValueError, KeyError, TypeError, AttributeError) as exc:
                        await send(
                            ws,
                            {
                                "type": "error",
                                "error": store.runtime.coerce(exc, "command.error"),
                                "id": body.get("id") if isinstance(body, dict) else None,
                            },
                        )
        finally:
            clients.discard(ws)
        return ws

    async def upload(request):
        reader = await request.multipart()
        part = await reader.next()
        if part is None or not part.filename:
            raise ValueError("Expected multipart file")
        content = bytearray()
        while chunk := await part.read_chunk():
            content.extend(chunk)
            if len(content) > MAX_UPLOAD:
                raise web.HTTPRequestEntityTooLarge(max_size=MAX_UPLOAD, actual_size=len(content))
        asset = await asyncio.to_thread(
            ingest,
            root,
            part.filename,
            bytes(content),
            request.query.get("kind", "image"),
            **media_options(store.snapshot()["settings"], store.runtime),
        )
        store.patch({"assets": {asset["id"]: asset}})
        return web.json_response(asset, status=201)

    async def export_template(request):
        template = store.get()["overlays"].get(request.match_info["id"])
        if template is None:
            raise web.HTTPNotFound(text="Unknown overlay")
        output = BytesIO()
        with ZipFile(output, "w") as archive:
            archive.writestr("template.json", json.dumps(template))
            names = set()
            for ref in asset_refs(template):
                path = checked_path(root, ref)
                if path.name == "manifest.json":
                    manifest = loop_manifest(path.read_bytes())
                    names.add(ref)
                    names.update(
                        (path.parent / frame).relative_to(root).as_posix()
                        for frame in manifest["frames"]
                    )
                else:
                    names.add(ref)
            for name in sorted(names):
                archive.write(checked_path(root, name), name)
        return web.Response(body=output.getvalue(), content_type="application/zip")

    async def import_template(request):
        limit = archive_limit(store.snapshot()["settings"], store.runtime)
        payload = bytearray()
        async for chunk in request.content.iter_chunked(64 * 1024):
            payload.extend(chunk)
            if len(payload) > limit:
                raise web.HTTPRequestEntityTooLarge(max_size=limit, actual_size=len(payload))
        return web.json_response(
            await asyncio.to_thread(import_archive, store, payload), status=201
        )

    async def preview(request):
        template = store.get()["overlays"].get(request.match_info["id"])
        if template is None:
            raise web.HTTPNotFound(text="Unknown overlay")
        image = await asyncio.to_thread(
            overlay.render_preview, template, store.get()["now_playing"], (640, 360)
        )
        output = BytesIO()
        image.save(output, "PNG")
        return web.Response(body=output.getvalue(), content_type="image/png")

    async def stage_command(request):
        ack = store.runtime.enqueue_command(await request.json())
        return web.json_response(ack, status=202)

    async def command_result(request):
        key = request.match_info["id"]
        # HTTP paths are strings; permit integer correlation ids too.
        result = store.runtime.command_result(key)
        if result is None:
            try:
                result = store.runtime.command_result(int(key))
            except ValueError:
                pass
        if result is None:
            raise web.HTTPNotFound(text="Command result is not available")
        return web.json_response(store.runtime.coerce(result, "command_result"))

    async def stage_status(request):
        return web.json_response(store.runtime.coerce(store.runtime.status(), "status"))

    async def stage_image(request):
        result = store.runtime.image(request.match_info["name"])
        if result is None:
            raise web.HTTPNotFound(text="Image is not available")
        content, content_type = result
        return web.Response(body=content, content_type=content_type)

    async def asset_file(request):
        return web.FileResponse(checked_path(root, "assets/" + request.match_info["path"]))

    async def schemas(request):
        return web.json_response(SCHEMAS)

    source_web = Path(__file__).resolve().parents[2] / "web"
    static = (
        Path(web_dir)
        if web_dir
        else (
            source_web
            if source_web.exists()
            else Path(sysconfig.get_path("data")) / "share/visualz/web"
        )
    )

    async def index(request):
        return web.FileResponse(static / "index.html")

    app.router.add_get("/api/stage/result/{id}", command_result)
    app.router.add_get("/api/stage/status", stage_status)
    app.router.add_post("/api/stage/command", stage_command)
    app.router.add_get("/api/stage/image/{name}", stage_image)
    app.router.add_get("/ws", websocket)
    app.router.add_get("/api/schemas", schemas)
    app.router.add_get("/api/state", state)
    app.router.add_patch("/api/state", state)
    app.router.add_post("/api/blackout", blackout)
    app.router.add_post("/api/assets", upload)
    app.router.add_post("/api/overlays/import", import_template)
    app.router.add_post("/api/overlays/{action:next|prev|clear|order}", slides)
    app.router.add_get("/api/overlays/{id}/export", export_template)
    app.router.add_get("/api/overlays/{id}/preview", preview)
    app.router.add_post("/api/{collection}/{id}/live", live)
    for method in ("GET", "PUT", "PATCH", "DELETE"):
        app.router.add_route(method, "/api/{collection}/{id}", item)
    for name in ("settings", "now_playing"):
        for method in ("GET", "PATCH"):
            app.router.add_route(method, "/api/{section:" + name + "}", section)
    for method in ("GET", "POST"):
        app.router.add_route(method, "/api/{collection}", collection)
    app.router.add_get("/assets/{path:.*}", asset_file)
    app.router.add_get("/", index)
    app.router.add_get("/control", index)
    app.router.add_static("/web", static)
    return app


class Server:
    """Server thread lifecycle. start() reports bind failures; close() joins cleanly."""

    def __init__(self, store, port=5211, telemetry=None):
        self.store, self.port, self.telemetry = store, port, telemetry
        self.loop = None
        self.error = None
        self.ready = threading.Event()

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.ready.wait(10)
        if self.error:
            raise RuntimeError(f"Control server failed: {self.error}") from self.error
        if not self.ready.is_set():
            raise RuntimeError("Control server start timed out")

    def _run(self):
        async def serve():
            runner = web.AppRunner(create_app(self.store, self.telemetry))
            try:
                await runner.setup()
                await web.TCPSite(runner, "0.0.0.0", self.port).start()
                self.ready.set()
                await self.stop.wait()
            finally:
                await runner.cleanup()

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.stop = asyncio.Event()
        try:
            self.loop.run_until_complete(serve())
        except Exception as exc:
            self.error = exc
            self.ready.set()
        finally:
            self.loop.close()

    def close(self):
        if self.loop and self.thread.is_alive():
            self.loop.call_soon_threadsafe(self.stop.set)
            self.thread.join(10)
