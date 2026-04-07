"""Tiny local HTTP bridge that redirects to `obsidian://` URLs.

Telegram rejects custom URL schemes in message entities and inline buttons,
so we expose an http://127.0.0.1:PORT/open?vault=X&file=Y endpoint that
replies with an HTTP 302 to the actual `obsidian://open?...` URL. Desktop
browsers (and macOS Telegram's link handler) then hand the custom scheme
off to the Obsidian app.
"""

from __future__ import annotations

from urllib.parse import quote

import structlog
from aiohttp import web

logger = structlog.get_logger()


async def _open_handler(request: web.Request) -> web.Response:
    vault = request.query.get("vault", "")
    file = request.query.get("file", "")
    if not vault or not file:
        return web.Response(status=400, text="missing vault or file query param")

    # Re-encode components to be safe (clients may pass them already encoded).
    obsidian_url = f"obsidian://open?vault={quote(vault, safe='')}&file={quote(file, safe='/')}"

    # Meta refresh + JS fallback so clicks that land in a browser still launch Obsidian.
    html = (
        "<!doctype html><html><head>"
        f'<meta http-equiv="refresh" content="0; url={obsidian_url}">'
        f'<script>window.location.replace({obsidian_url!r});</script>'
        "</head><body>"
        f'<p>Opening Obsidian… <a href="{obsidian_url}">tap here</a> if nothing happens.</p>'
        "</body></html>"
    )
    return web.Response(
        status=302,
        headers={"Location": obsidian_url},
        body=html,
        content_type="text/html",
    )


async def _health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


class RedirectServer:
    """aiohttp server that exposes the /open redirect endpoint."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/open", _open_handler)
        app.router.add_get("/health", _health)

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logger.info("redirect_server.started", host=self.host, port=self.port)

    async def stop(self) -> None:
        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        logger.info("redirect_server.stopped")

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"
