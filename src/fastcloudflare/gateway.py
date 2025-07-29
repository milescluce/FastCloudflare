import asyncio
import time
from pathlib import Path
from typing import Any, Type

import httpx
import starlette.responses
from fastapi import APIRouter, FastAPI
from loguru import logger as log
from propcache import cached_property
from starlette.requests import Request
from toomanyports import PortManager
from toomanysessions import SessionedServer, Session, User
from toomanythreads import ThreadedServer

from fastcloudflare.src.fastcloudflare import Cloudflare

DEBUG = True

class Gateway(Cloudflare, SessionedServer):
    def __init__(
        self,
        app: FastAPI | SessionedServer | ThreadedServer,
        host: str = "localhost",
        port: int = PortManager().random_port(),
        session_name: str = "session",
        session_age: int = (3600 * 8),
        session_model: Type[Session] = Session,
        authentication_model: str | Type[APIRouter] | None = "msft",
        user_model: Type[User] = User,
        verbose: bool = DEBUG,
        **sessioned_server_kwargs,
    ):
        Cloudflare.__init__(self)
        SessionedServer.__init__(
            self,
            host = host,
            port = port,
            session_name = session_name,
            session_age = session_age,
            session_model = session_model,
            authentication_model = authentication_model,
            user_model = user_model,
            verbose = verbose,
            **sessioned_server_kwargs
        )
        self.app = app
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0, read=30.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20, keepalive_expiry=30.0),
            http2=False,
            headers={"Connection": "keep-alive"}
        )

        @self.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        async def forward(path: str, request: Request):
            url = f"{self.app.url}/{path}"

            try:
                # Use persistent client with keep-alive
                resp = await self.client.request(
                    request.method,
                    url,
                    headers={k: v for k, v in request.headers.items() if k.lower() not in {'host', 'content-length'}},
                    content=await request.body(),
                    params=request.query_params,
                    follow_redirects=True
                )

                # Clean headers that cause issues
                headers = {}
                for k, v in resp.headers.items():
                    if k.lower() not in {'content-encoding', 'transfer-encoding', 'content-length', 'connection'}:
                        headers[k] = v

                # Force connection keep-alive in response
                headers['Connection'] = 'keep-alive'
                headers['Keep-Alive'] = 'timeout=60, max=1000'

                return starlette.responses.Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    headers=headers
                )

            except Exception as e:
                if self.verbose:
                    log.error(f"Gateway forward error: {e}")

            return starlette.responses.Response(
                content=f"Gateway Error: {str(e)}",
                status_code=502,
                headers={"content-type": "text/plain"}
            )

        self.app.thread.start()

    @cached_property
    def url(self):
        return f"http://{self.domain_name}"

    async def launch(self):
        loc = self.thread
        glo = await self.cloudflared_thread
        loc.start()
        glo.start()

if __name__ == "__main__":
    app = ThreadedServer()
    g = Gateway(app)
    asyncio.run(g.launch())