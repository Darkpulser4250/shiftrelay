"""Policy identity without changing the upstream routing destination."""
from mitmproxy.proxy.mode_specs import WireGuardMode
from shiftrelay.policy import HOST


def policy_host(flow):
    if not isinstance(flow.client_conn.proxy_mode, WireGuardMode):
        return flow.request.host.lower().rstrip('.')
    # Transparent transports keep request.host as the destination IP. Using that
    # IP misses domain rules; changing it could accidentally reroute requests.
    try:
        host = flow.request.pretty_host.lower().rstrip('.')
    except (ValueError, AttributeError):
        return ''
    if not HOST.fullmatch(host):
        return ''
    if flow.request.scheme == 'https':
        sni = (flow.client_conn.sni or '').lower().rstrip('.')
        if host != sni:
            # Never let an arbitrary Host header expand HTTPS inspection scope.
            return ''
    return host
