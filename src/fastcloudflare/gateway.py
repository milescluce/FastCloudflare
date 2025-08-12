import time
from pathlib import Path
from typing import Type

from fastapi import FastAPI
from loguru import logger as log
from propcache import cached_property
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from toomanyports import PortManager
from toomanysessions import SessionedServer, Session, User
from toomanythreads import ThreadedServer

from . import Cloudflare
from . import CloudflareAPIConfig

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
            user_model: Type[User] = User,
            user_whitelist: list = None,
            tenant_whitelist: list = None,
            verbose: bool = DEBUG,
            **sessioned_server_kwargs,
    ):
        self.cwd = Path.cwd()
        self.cfg_file = self.cwd / "cloudflare_api.toml"
        cfg = CloudflareAPIConfig.create(
            self.cfg_file
        )
        Cloudflare.__init__(
            self,
            config=cfg
        )
        self.app = app
        self.config.info.service_url = f"http://{host}:{port}"
        log.debug(f"{self}: Set service_url: {self.config.info.service_url}")
        self.config.write()
        SessionedServer.__init__(
            self,
            host=host,
            port=port,
            session_name=session_name,
            session_age=session_age,
            session_model=session_model,
            user_model=user_model,
            user_whitelist=user_whitelist,
            tenant_whitelist=tenant_whitelist,
            verbose=verbose,
            **sessioned_server_kwargs
        )

        @self.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        async def forward(path: str, request: Request):
            url = f"{self.app.url}/{path}"
            log.debug(f"{self}: Attempting request to {url}")

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

                response = Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    headers=headers
                )
                # if resp.content == {"detail": "Not Found"}: response.status_code = 404

                # Handle 404s with animated popup
                if response.status_code == 404:
                    return HTMLResponse(
                        self.popup_404(
                            message=f"The page '{request.url.path}' could not be found."
                        ),
                        status_code=404
                    )

                return response

            except Exception as e:
                log.error(f"{self}: Error processing request: {e}")
                return HTMLResponse(
                    self.popup_error(
                        error_code=500,
                        message="An unexpected error occurred while processing your request."
                    ),
                    status_code=500
                )

        self.app.thread.start()

    @cached_property
    def url(self):
        return f"https://{self.config.info.domain}"

    def launch(self):
        loc = self.thread
        glo = self.cloudflared_thread
        loc.start()
        glo.start()