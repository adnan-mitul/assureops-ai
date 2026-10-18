"""Destination policy for every request a connector makes.

A connection is pinned to one origin. Requests are built from that origin plus
a path the profile is allowed to use; redirects are never followed, so a
target cannot steer the runner to internal addresses. Loopback, private,
link-local and metadata addresses are refused unless the deployment
explicitly allows private targets (local labs, private networks).
"""

import ipaddress
import socket
from urllib.parse import urlsplit

METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal", "100.100.100.200", "fd00:ec2::254"}


class EgressDenied(Exception):
    pass


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise EgressDenied("target URL must be http(s) with a host")
    if parts.username or parts.password:
        raise EgressDenied("credentials in the target URL are not allowed; use connector secrets")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise EgressDenied("target URL must be an origin (scheme://host[:port]) without a path")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    host = parts.hostname.lower()
    return f"{parts.scheme}://{host}:{port}" if ":" not in host else f"{parts.scheme}://[{host}]:{port}"


def _addresses(host: str) -> list[ipaddress._BaseAddress]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise EgressDenied(f"target host does not resolve: {exc.__class__.__name__}")
    return [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]


def classify_host(host: str) -> str:
    """public | private (loopback/RFC1918/ULA/link-local) | metadata."""
    if host.lower() in METADATA_HOSTS:
        return "metadata"
    kinds = set()
    for addr in _addresses(host):
        if str(addr) in METADATA_HOSTS:
            kinds.add("metadata")
        elif addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_reserved or addr.is_unspecified:
            kinds.add("private")
        else:
            kinds.add("public")
    if "metadata" in kinds:
        return "metadata"
    return "private" if "private" in kinds else "public"


def check_target(url: str, *, allow_private: bool) -> dict:
    """Validate a connection's target before anything is sent to it."""
    origin = origin_of(url)
    host = urlsplit(url).hostname
    kind = classify_host(host)
    if kind == "metadata":
        raise EgressDenied("cloud metadata addresses are never valid targets")
    if kind == "private" and not allow_private:
        raise EgressDenied("private or loopback targets are not reachable from this deployment; use an authorized connector on a reachable address")
    return {"origin": origin, "address_class": kind}


def check_path(path: str, allowed_prefixes: list[str], method: str, allowed_methods: list[str]) -> None:
    if not isinstance(path, str) or not path.startswith("/") or "://" in path or "\\" in path:
        raise EgressDenied(f"request path {path!r} is not a relative path")
    clean = path.split("?", 1)[0]
    if any(seg in ("..", ".") for seg in clean.split("/")):
        raise EgressDenied(f"request path {path!r} contains traversal segments")
    if method.upper() not in {m.upper() for m in allowed_methods}:
        raise EgressDenied(f"method {method} is outside the authorized scope")
    if not any(clean == p or clean.startswith(p.rstrip("/") + "/") for p in allowed_prefixes):
        raise EgressDenied(f"path {clean} is outside the authorized scope")
