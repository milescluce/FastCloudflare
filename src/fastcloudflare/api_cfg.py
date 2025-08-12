from pathlib import Path

from toomanyconfigs import RoutesConfig, HeadersConfig, VarsConfig, CWD, API, APIConfig, Shortcuts, TOMLSubConfig


class CloudflareAPIHeaders(HeadersConfig):
    authorization: str = "Bearer ${CLOUDFLARE_API_TOKEN}"


class CloudflareShortcuts(Shortcuts):
    tunnel: str = "/accounts/${ACCOUNT_ID}/cfd_tunnel"
    dns_record: str = "/zones/${ZONE_ID}/dns_records"


class CloudflareAPIRoutes(RoutesConfig):
    base: str = "https://api.cloudflare.com/client/v4"
    shortcuts: CloudflareShortcuts


class CloudflareAPIVars(VarsConfig):
    cloudflare_api_token: str = None
    cloudflare_email: str = None
    account_id: str = None
    zone_id: str = None


class Info(TOMLSubConfig):
    domain: str = None
    service_url: str = ""


class Tunnel(TOMLSubConfig):
    name: str = ""
    id: str = ""
    token: str = ""


class CloudflareAPIConfig(APIConfig):
    headers: CloudflareAPIHeaders
    routes: CloudflareAPIRoutes
    vars: CloudflareAPIVars
    info: Info
    tunnel: Tunnel


class CloudflareAPI(CWD, API):
    def __init__(self, config=None):
        CWD.__init__(self, "cloudflare_api.toml")
        src: Path = self.cloudflare_api  # type: ignore
        if not config:
            config = CloudflareAPIConfig.create(src)
        API.__init__(self, config)
        self.config.apply_variable_substitution()

    def __repr__(self):
        return "[Cloudflare.API]"


if __name__ == "__main__":
    CloudflareAPI()
