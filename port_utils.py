import socket
from urllib.parse import urlparse


BROWSER_UNSAFE_PORTS = {
    1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69, 77, 79, 87, 95,
    101, 102, 103, 104, 109, 110, 111, 113, 115, 117, 119, 123, 135, 137, 139, 143, 161,
    179, 389, 427, 465, 512, 513, 514, 515, 526, 530, 531, 532, 540, 548, 554, 556, 563,
    587, 601, 636, 989, 990, 993, 995, 1719, 1720, 1723, 2049, 3659, 4045, 5060, 5061,
    6000, 6566, 6665, 6666, 6667, 6668, 6669, 6697, 10080,
}

DEFAULT_PORT_BASE = 5050
DEFAULT_PORT_STEP = 10


def is_browser_safe_port(port):
    try:
        return int(port) not in BROWSER_UNSAFE_PORTS
    except (TypeError, ValueError):
        return False


def resolve_port(preferred_port, host="127.0.0.1"):
    port = max(int(preferred_port), 1024)
    while True:
        if not is_browser_safe_port(port):
            port += 1
            continue

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if sock.connect_ex((host, port)) != 0:
                return port
        port += 1


def next_preferred_port(used_ports, start=DEFAULT_PORT_BASE, step=DEFAULT_PORT_STEP):
    used = {int(port) for port in used_ports if isinstance(port, int) or str(port).isdigit()}
    candidate = start

    while True:
        if candidate not in used and is_browser_safe_port(candidate):
            return candidate
        candidate += step


def port_from_url(url):
    if not url:
        return None
    try:
        parsed = urlparse(url)
        return parsed.port
    except ValueError:
        return None
