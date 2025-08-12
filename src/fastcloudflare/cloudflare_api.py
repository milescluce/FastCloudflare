import threading
from functools import cached_property

from loguru import logger as log
from toomanyconfigs.api import Response
from toomanythreads import ManagedThread

from . import cloudflared, CloudflareAPI, Tunnel
from .api_cfg import CloudflareAPIConfig


class Cloudflare(CloudflareAPI):
    def __init__(self, config: CloudflareAPIConfig = None):
        super().__init__(config)
        _ = self.tunnel

    def __repr__(self):
        return f"[Cloudflare.Gateway]"

    @cached_property
    def domain_name(self) -> str:
        domain = self.config.info.domain
        n = domain.split(".")
        return n[0]

    # noinspection PyTypeChecker
    @cached_property
    def tunnel(self) -> Tunnel:
        log.debug(f"{self}: Attempting to initialize tunnel...")
        name = f"{self.domain_name}-tunnel"
        name = name.replace(".", "-")
        if self.config.tunnel.id == "":
            log.warning(f"{self}: No tunnel written to disk! Patching...")
            post = self.sync_api_post(
                route="tunnel",
                json={
                    "name": f"{name}",
                    "config_src": "cloudflare"
                },
                force_refresh=True
            )
            if post.status == 200:
                log.success(f"{self}: Tunnel successfully  created!")
                meta = post.body["result"]
                tunnel = Tunnel.create(name=name, id=meta["id"], token=meta["token"], meta=meta)
                self.config.tunnel = tunnel
                self.config.write()
                log.success(f"{self}: Successfully found tunnel! {self.config.tunnel}")
                return tunnel
            if post.status == 409:
                meta = None
                log.warning(f"{self}: Tunnel for {name} already exists!")
                get: Response = self.sync_api_get(
                    route="tunnel",
                    force_refresh=True
                )
                get: list = get.body["result"]
                for item in get:
                    log.debug(f"{self}: Scanning for {name} in {item}...\n  - item_name={item["name"]}")
                    if item["name"] == name:
                        meta = item
                        log.success(f"{self}: Successfully found {name}!\n  - metadata={item}")
                        break
                cfd = cloudflared(f"'cloudflared tunnel token {meta["id"]}'", headless=True)
                tunnel = Tunnel(name=name, id=meta["id"], token=cfd.output, meta=meta)
                self.config.tunnel = tunnel
                self.config.write()
                log.success(f"{self}: Successfully found tunnel! {self.config.tunnel}")
                return tunnel
            else:
                raise ConnectionRefusedError(post.body)
        else:
            log.debug(f"{self}: Found tunnel creds in {self.config._path}!")
            return self.config.tunnel

    @cached_property
    def service_url(self):
        url = self.config.info.service_url
        if (not url) or (url == ""): raise RuntimeError
        log.debug(f"{self}: Loaded service url {url} from config!")
        return url

    @cached_property
    def connect_server(self):
        try:
            if self.config.info.service_url == "": raise RuntimeError(
                f"Can't launch cloudflared without a service to launch it to!")
        except RuntimeError:
            try:
                self.config.info.service_url = self.service_url
            except AttributeError:
                raise RuntimeError
        ingress_cfg = {
            "config": {
                "ingress": [
                    {
                        "hostname": f"{self.config.info.domain}",
                        "service": f"{self.config.info.service_url}",
                        "originRequest": {}
                    },
                    {
                        "service": "http_status:404"
                    }
                ]
            }
        }
        out = self.sync_api_put(
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

    @cached_property
    def dns_record(self):
        # record_name = "phazebreak.work"
        # records = asyncio.run(self.receptionist.get("dns_record", append="?zone_id=$ZONE_ID"))
        # record_id = next(r["id"] for r in records.content["result"] if r["domain_name"] == record_name)
        # asyncio.run(self.receptionist.delete(f"dns_record", append=f"{record_id}"))

        name = self.config.info.domain
        cfg = {
            "type": "CNAME",
            "proxied": True,
            "domain_name": f"{name}",
            "content": f"{self.config.tunnel.id}.cfargotunnel.com"
        }
        out = self.sync_api_post(route="dns_record", json=cfg, force_refresh=True)
        if out.status == 400 and out.body["errors"][0]["code"] == 81053:
            log.warning(f"{self}DNS Request already exists!\nreq={out}")
            headers = {
                f"X-Auth-Email": f"{self.config.vars["cloudflare_email"]}",
                f"X-Auth-Key": f"{self.config.vars["cloudflare_api_token"]}"
            }

            recs = self.sync_api_get(route="dns_record", force_refresh=True)
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
            rec = self.sync_api_request(method="patch", route="dns_record", append=f"/{rec_id}", json=cfg,
                                        force_refresh=True)  # , override_headers=headers)
            log.debug(rec)
        if out.status == 200:
            log.success(f"{self} Successfully updated Ingress Config!:\nreq={out}")
        return out

    @cached_property
    def cloudflared_thread(self) -> threading.Thread:
        _ = self.connect_server
        _ = self.dns_record

        @ManagedThread
        def _launcher():
            log.debug(f"Attempting to run tunnel...")
            cloudflared(f"'cloudflared tunnel info {self.tunnel.id}'", headless=True)
            cloudflared(f"'cloudflared tunnel run --token {self.tunnel.token}'", headless=False)

        return _launcher
