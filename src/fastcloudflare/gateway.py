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
from fastmicroservices import Macroservice, Microservice

from . import Cloudflare
from . import CloudflareAPIConfig

DEBUG = True


class Gateway(Macroservice, SessionedServer, Cloudflare):
    def __init__(
            self,
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
        Macroservice.__init__(
            self
        )

    @cached_property
    def url(self):
        return f"https://{self.config.info.domain}"

    def launch(self):
        loc = self.thread
        glo = self.cloudflared_thread
        loc.start()
        glo.start()