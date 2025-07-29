import threading
import time
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import toml
from async_property import async_cached_property
from loguru import logger as log
from pyzurecli import PyzureServer
# from pyzurecli import PyzureServer
from toomanysessions import SessionedServer
from toomanythreads import ManagedThread, ThreadedServer

from . import cloudflared
from toomanyconfigs import TOMLDataclass, API, VarsConfig, HeadersConfig, RoutesConfig, APIConfig

@dataclass
class CloudflareAPIHeaders(HeadersConfig):
    authorization: str = "Bearer $CLOUDFLARE_API_TOKEN"

@dataclass
class CloudflareAPIRoutes(RoutesConfig):
    base: str = "https://api.cloudflare.com/client/v4"

@dataclass
class CloudflareAPIVars(TOMLDataclass):
    cloudflare_api_token: str = None
    cloudflare_email: str = None
    account_id: str = None
    zone_id: str = None

class CloudflareAPI(API):
    def __init__(self):
        self.cfg_file = Path.cwd() / "cloudflare_api.toml"
        self.vars_file = Path.cwd() / "cloudflare_vars.toml"
        self.routes = {
            "tunnel": "/accounts/$ACCOUNT_ID/cfd_tunnel",
            "dns_record": "/zones/$ZONE_ID/dns_records"
        }
        config = APIConfig.create(
            source=self.cfg_file,
            headers=CloudflareAPIHeaders(),
            routes=CloudflareAPIRoutes(routes=self.routes),
            vars=CloudflareAPIVars.create(self.vars_file),
        )
        super().__init__(config)

    def __repr__(self):
        return "[Cloudflare.API]"

@dataclass
class Info(TOMLDataclass):
    domain: str = None
    service_url: str = ""

@dataclass
class Tunnel(TOMLDataclass):
    name: str = ""
    id: str = ""
    token: str = ""
    meta: dict = field(default_factory=dict)

info_path = Path.cwd() / "cloudflared_info.toml"
tunnel_path = Path.cwd() / "cloudflared_tunnel.toml"

@dataclass
class CloudflaredCFG(TOMLDataclass):
    info: Info = field(default_factory=Info.create(info_path))
    tunnel: Tunnel = field(default_factory=Tunnel.create(tunnel_path))

    def __repr__(self):
        return "[Cloudflare.CLI]"

class Cloudflare(CloudflareAPI):
    def __init__(self, app: ThreadedServer | SessionedServer | PyzureServer = None, url = None):
        self.app = app
        self.url = url or ""
        super().__init__()
        self.cloudflared_cfg = CloudflaredCFG.create(Path.cwd())

    def __repr__(self):
        return f"[Cloudflare.Gateway]"

    @cached_property
    def domain_name(self) -> str:
        domain = self.cloudflared_cfg.info.domain
        n = domain.split(".")
        return n[0]

    # noinspection PyTypeChecker
    @async_cached_property
    async def tunnel(self) -> Tunnel:
        name = f"{self.domain_name}-tunnel"
        name = name.replace(".", "-")
        if self.cloudflared_cfg.tunnel.id == "":
            post = await self.api_post(
                route="tunnel",
                json={
                    "domain_name": f"{name}",
                    "config_src": "cloudflare"
                },
                force_refresh=True
            )
            if post.status == 200:
                meta = post.body["result"]
                tunnel = Tunnel(name=name, id=meta["id"], token=meta["token"], meta=meta)
                self.cloudflared_cfg.tunnel = tunnel
                self.cloudflared_cfg.write()
                log.success(f"{self}: Successfully found tunnel! {self.cloudflared_cfg.tunnel}")
                return tunnel
            if post.status == 409:
                meta = None
                log.warning(f"{self}: Tunnel for {name} already exists!")
                get = await self.api_get(
                    route="tunnel",
                    force_refresh=True
                )
                get: list = get.body["result"]
                for item in get:
                    log.debug(f"{self}: Scanning for {name} in {item}...\n  - item_name={item["domain_name"]}")
                    if item["domain_name"] == name:
                        meta = item
                        log.success(f"{self}: Successfully found {name}!\n  - metadata={item}")
                        break
                cfd = cloudflared(f"'cloudflared tunnel token {meta["id"]}'", headless=True)
                tunnel = Tunnel(name=name, id=meta["id"], token=cfd.output, meta=meta)
                self.cloudflared_cfg.tunnel = tunnel
                self.cloudflared_cfg.write()
                log.success(f"{self}: Successfully found tunnel! {self.cloudflared_cfg.tunnel}")
                return tunnel
        else:
            log.debug(f"{self}: Found tunnel creds in {self.cloudflared_cfg.path}!")
            return self.cloudflared_cfg.tunnel

    @async_cached_property
    async def connect_server(self):
        try:
            if self.cloudflared_cfg.info.service_url == "": raise RuntimeError(
                f"Can't launch cloudflared without a service to launch it to!")
        except RuntimeError:
            try:
                self.cloudflared_cfg.info.service_url = getattr(self.app, "url", self.url)
            except AttributeError:
                raise RuntimeError
        ingress_cfg = {
            "config": {
                "ingress": [
                    {
                        "hostname": f"{self.cloudflared_cfg.info.domain}",
                        "service": f"{self.cloudflared_cfg.info.service_url}",
                        "originRequest": {}
                    },
                    {
                        "service": "http_status:404"
                    }
                ]
            }
        }
        out = await self.api_put(
            route="tunnel",
            append=f"/{self.tunnel.id}/configurations",
            json=ingress_cfg,
            force_refresh=True
        )
        if out.status == 400:
            log.error(f"{self}Failed Ingress Config request={out}")
            raise RuntimeError
        if out.status == 200:
            log.success(f"{self} Successfully updated Ingress Config!:\nreq={out}")
        return out

    @async_cached_property
    async def dns_record(self):
        # record_name = "phazebreak.work"
        # records = asyncio.run(self.receptionist.get("dns_record", append="?zone_id=$ZONE_ID"))
        # record_id = next(r["id"] for r in records.content["result"] if r["domain_name"] == record_name)
        # asyncio.run(self.receptionist.delete(f"dns_record", append=f"{record_id}"))

        name = self.cloudflare_cfg.info.domain
        cfg = {
            "type": "CNAME",
            "proxied": True,
            "domain_name": f"{name}",
            "content": f"{self.cloudflare_cfg.tunnel.id}.cfargotunnel.com"
        }
        out = await self.api_post(route="dns_record", json=cfg, force_refresh=True)
        if out.status == 400 and out.body["errors"][0]["code"] == 81053:
            log.warning(f"{self}DNS Request already exists!\nreq={out}")
            headers = {
                f"X-Auth-Email": f"{self.vars["cloudflare_email"]}",
                f"X-Auth-Key": f"{self.vars["cloudflare_api_token"]}"
            }

            recs = await self.api_get(route="dns_record", force_refresh=True)
            get: list = recs.body["result"]
            rec = None
            for item in get:
                log.debug(f"{self}: Scanning for {name} in {item}...\n  - item_name={item["domain_name"]}")
                if item["domain_name"] == name:
                    rec = item
                    log.success(f"{self}: Successfully found {name} in DNS Records!\n  - metadata={item}")
                    break
            if rec is None: raise RuntimeError
            rec_id = rec["id"]
            log.debug(f"{name}'s DNS Record is {rec_id}")
            rec = await self.api_request(method="patch", route="dns_record", append=f"/{rec_id}", json=cfg,
                                         force_refresh=True)  # , override_headers=headers)
            log.debug(rec)
        if out.status == 200:
            log.success(f"{self} Successfully updated Ingress Config!:\nreq={out}")
        return out

    @async_cached_property
    async def cloudflared_thread(self) -> threading.Thread:
        await self.tunnel, await self.connect_server, await self.dns_record

        @ManagedThread
        def _launcher():
            log.debug(f"Attempting to run tunnel...")
            cloudflared(f"'cloudflared tunnel info {self.cloudflared_cfg.tunnel.id}'", headless=True)
            cloudflared(f"'cloudflared tunnel run --token {self.cloudflared_cfg.tunnel.token}'", headless=False)

        return _launcher