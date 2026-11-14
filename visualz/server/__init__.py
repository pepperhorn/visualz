"""REST /api and /ws. WS receives {type:patch, patch:{...}} and emits full state.

State messages: {type:state,state:{...}}. Telemetry is a separate volatile message
{type:telemetry,audio:{...},stage:{...}} at 10 Hz; it is never persisted.
Collections are /api/{scenes,overlays,picture_sets}; POST creates, PUT replaces,
PATCH merges, DELETE removes. POST /api/overlays/{id}/live takes a slide live;
/api/overlays/{next,prev,clear,order} manages the slide list. Scene /{id}/live
recalls it. POST /api/assets?kind=image|logo|clip|font accepts a multipart file.
Overlay /{id}/export returns a ZIP; POST /api/overlays/import imports ZIP bytes.
"""

import asyncio
import json
import sysconfig
import threading
from io import BytesIO
from pathlib import Path, PurePosixPath
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from aiohttp import WSMsgType, web

from visualz import overlay
from visualz.media import MAX_UPLOAD, ingest
from visualz.schema import SCHEMAS, validate
from visualz.state import COLLECTIONS, merge


def asset_refs(value):
    if isinstance(value, str) and value.startswith("assets/"):
        return {value}
    if isinstance(value, dict):
        return set().union(set(), *(asset_refs(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(set(), *(asset_refs(v) for v in value))
    return set()


def checked_path(root, name):
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or not path.parts
        or path.parts[0] != "assets"
    ):
        raise ValueError("Invalid asset path")
    result = (root / name).resolve()
    if not result.is_relative_to((root / "assets").resolve()):
        raise ValueError("Asset path escapes data directory")
    return result


@web.middleware
async def errors(request, handler):
    try:
        return await handler(request)
    except (ValueError, KeyError, TypeError, BadZipFile) as exc:
        return web.json_response({"error": str(exc)}, status=400)


def create_app(store, telemetry=None, web_dir=None):
    """Build app; optional telemetry() returns JSON-safe audio/stage status."""
    app = web.Application(client_max_size=MAX_UPLOAD, middlewares=[errors])
    clients = set()
    telemetry = telemetry or (lambda: {"audio": {}, "stage": {"fps": 0, "devices": []}})
    root = store.data_dir

    async def broadcast(state):
        message = {"type": "state", "state": state}
        for ws in tuple(clients):
            try:
                await ws.send_json(message)
            except (ConnectionError, RuntimeError):
                clients.discard(ws)

    async def lifecycle(app):
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        unsubscribe = store.subscribe(
            lambda state: loop.call_soon_threadsafe(queue.put_nowait, state)
        )

        async def states():
            while True:
                await broadcast(await queue.get())

        async def meters():
            while True:
                await asyncio.sleep(0.1)
                for ws in tuple(clients):
                    try:
                        await ws.send_json({"type": "telemetry", **telemetry()})
                    except (ConnectionError, RuntimeError):
                        clients.discard(ws)

        tasks = [asyncio.create_task(states()), asyncio.create_task(meters())]
        yield
        unsubscribe()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for ws in tuple(clients):
            await ws.close()

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
                    "mode_params",
                    "look",
                    "quality",
                    "picture_set",
                    "source_asset",
                ):
                    if field in scene:
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
                    try:
                        body = json.loads(msg.data)
                        if body.get("type") != "patch":
                            raise ValueError("Expected patch message")
                        store.patch(body["patch"])
                    except (ValueError, KeyError, TypeError, AttributeError) as exc:
                        await ws.send_json({"type": "error", "error": str(exc)})
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
            ingest, root, part.filename, bytes(content), request.query.get("kind", "image")
        )
        store.patch({"assets": {asset["id"]: asset}})
        return web.json_response(asset, status=201)

    async def export_template(request):
        template = store.get()["overlays"][request.match_info["id"]]
        output = BytesIO()
        with ZipFile(output, "w") as archive:
            archive.writestr("template.json", json.dumps(template))
            names = set()
            for ref in asset_refs(template):
                path = checked_path(root, ref)
                if path.name == "manifest.json":
                    names.update(
                        p.relative_to(root).as_posix() for p in path.parent.iterdir() if p.is_file()
                    )
                else:
                    names.add(ref)
            for name in sorted(names):
                archive.write(checked_path(root, name), name)
        return web.Response(body=output.getvalue(), content_type="application/zip")

    async def import_template(request):
        payload = await request.read()

        def unpack():
            with ZipFile(BytesIO(payload)) as archive:
                members = archive.infolist()
                if len(members) > 300 or sum(m.file_size for m in members) > MAX_UPLOAD:
                    raise ValueError("Archive exceeds expanded size or file count limit")
                if len({m.filename for m in members}) != len(members):
                    raise ValueError("Duplicate archive entries")
                template = validate("overlay", json.loads(archive.read("template.json")))
                mapping = {}
                blobs = {}
                prefix = f"assets/{uuid4().hex}"
                for member in members:
                    if member.filename == "template.json":
                        continue
                    checked_path(root, member.filename)
                    if member.is_dir() or (member.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError("Only regular asset files are accepted")
                    mapping[member.filename] = (
                        prefix + "/" + member.filename.removeprefix("assets/")
                    )
                    blobs[member.filename] = archive.read(member)
                if not asset_refs(template) <= set(mapping):
                    raise ValueError("Archive is missing referenced assets")

                def remap(value):
                    if isinstance(value, str):
                        return mapping.get(value, value)
                    if isinstance(value, dict):
                        return {k: remap(v) for k, v in value.items()}
                    if isinstance(value, list):
                        return [remap(v) for v in value]
                    return value

                template = remap(template)
                if template["id"] in store.get()["overlays"]:
                    template["id"] = uuid4().hex
                validate("overlay", template)
                for name, content in blobs.items():
                    path = checked_path(root, mapping[name])
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                imported_assets = {}
                for ref in asset_refs(template):
                    asset_id = uuid4().hex
                    suffix = Path(ref).suffix.lower()
                    kind = (
                        "font"
                        if suffix in (".ttf", ".otf")
                        else ("logo" if suffix == ".json" else "image")
                    )
                    imported_assets[asset_id] = dict(
                        id=asset_id,
                        path=ref,
                        original=None,
                        kind=kind,
                        name=Path(ref).name,
                        warnings=[],
                    )
                store.patch({"overlays": {template["id"]: template}, "assets": imported_assets})
                return template

        return web.json_response(await asyncio.to_thread(unpack), status=201)

    async def preview(request):
        template = store.get()["overlays"][request.match_info["id"]]
        image = await asyncio.to_thread(
            overlay.render_preview, template, store.get()["now_playing"], (640, 360)
        )
        output = BytesIO()
        image.save(output, "PNG")
        return web.Response(body=output.getvalue(), content_type="image/png")

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
