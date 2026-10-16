"""The machine's network interfaces, and which may carry `--listen` (1.47.0, OPEN-DECISIONS.md "Without
Cloudflare", L4 refined by L13 L14, and L16 L17).

`--listen ADDR` puts a console's owner door on ONE address beyond loopback, and only on an overlay network
that already encrypts and admits by membership:

- **ZeroTier**: an interface whose name starts with `zt` (WSL's own node, L13: e.g. `ztexample0`, 10.147.17.0/24);
- **Tailscale**: `tailscale0`, or an address in 100.64.0.0/10 on an interface whose name starts with
  `tailscale`.

Refused by name, before any interface is looked at: `0.0.0.0` (every interface), any loopback address
(127/8 is what a console gets WITHOUT --listen), a public address that is not Tailscale's 100.64/10, IPv6,
and anything that is not one IPv4 address. An address that IS on this machine but on any other interface
(eth0, docker0, a br-* bridge, lo) is refused at once. An address on no interface yet is waited for (L16):
ZeroTier may come up after the console's service does.

`interfaces()` is the ONE discovery: [(name, ipv4, prefixlen, up)], one tuple per address, from an rtnetlink
address dump (every address, secondaries and aliases included; 1.47, C3) and SIOCGIFFLAGS per name: no
process is started and no `ip` command is run, so the one server's no-spawn rule holds. An address held by
an overlay AND by any other interface is refused (S3). Linux only: on another system `--listen` is refused
("comes with 1.48").

The check runs at start (and while waiting, L16) only. Nothing re-checks after the bind: an address moved to
eth0 later keeps its socket until the server restarts.

Tests replace the machine with `set_fake(...)`: code, never a flag, an environment variable or a file. Only
a fake may also let a loopback alias (127.0.0.2 on "ztfake0") through, so a real-socket test can listen
somewhere no test machine's ZeroTier is; nothing a user can type reaches that.
"""

from __future__ import annotations

import ipaddress
import socket
import struct
import sys
import time
from typing import Callable

SIOCGIFFLAGS = 0x8913
SIOCGIFADDR = 0x8915
SIOCGIFNETMASK = 0x891B
IFF_UP = 0x1
IFF_RUNNING = 0x40
TAILSCALE_NET = ipaddress.IPv4Network("100.64.0.0/10")
WAIT_SECONDS = 120   # L16: up to 2 minutes, then exit 1 for the service to restart it
POLL_SECONDS = 2
NOT_LINUX = "--listen comes with 1.48 on this system; on Linux and WSL it is here now (1.47)"

# The test hook: (provider of [(name, ipv4, prefixlen, up)], whether a loopback address may be accepted on a
# fake overlay interface). None: the machine itself. Set only through set_fake().
_fake: tuple[Callable[[], list], bool] | None = None


class ListenError(ValueError):
    """A --listen address refused, or never seen in time; the message names why."""


def set_fake(provider: Callable[[], list] | None, loopback_ok: bool = False) -> None:
    """Tests only: answer `interfaces()` from `provider` instead of this machine (None restores it).
    `loopback_ok` lets a loopback alias pass contract 1 when the fake puts it on a zt*/tailscale* interface."""
    global _fake
    _fake = None if provider is None else (provider, bool(loopback_ok))


def _ioctl(s: socket.socket, request: int, name: str) -> bytes:
    import fcntl   # POSIX only; imported here so the module loads (and refuses) on any system
    return fcntl.ioctl(s.fileno(), request, struct.pack("16s24x", name.encode("utf-8")[:15]))


def interfaces() -> list[tuple[str, str, int, bool]]:
    """Every IPv4 address on every interface: (name, address, prefix length, up), one tuple per address, so
    an interface with a secondary address (an alias) appears once per address. `up` is IFF_UP and
    IFF_RUNNING: a Docker bridge with no container is UP but not RUNNING (`ip` says "state DOWN"), and is
    reported down. [] off Linux.

    1.47 (C3, S3): the addresses come from one rtnetlink RTM_GETADDR dump (a socket, stdlib only, no process),
    which lists every address as `ip -4 addr` does. The ioctls of 1.47.0 saw only each interface's PRIMARY
    address, so an owner who picked a secondary ZeroTier address waited 2 minutes and exited 1 every time.
    Should netlink be unavailable, the ioctls remain, and say so (`seen_note`)."""
    if _fake is not None:
        return [(str(n), str(a), int(p), bool(u)) for n, a, p, u in _fake[0]()]
    if not sys.platform.startswith("linux"):
        return []
    try:
        found = [(socket.if_indextoname(i), a, p) for i, a, p in _netlink_addresses()]
    except OSError:
        return _primary_only()
    _seen["primary_only"] = False
    out = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for name, addr, prefix in found:
            try:
                flags = struct.unpack("H", _ioctl(s, SIOCGIFFLAGS, name)[16:18])[0]
            except OSError:
                continue   # gone since it was listed
            out.append((name, addr, prefix, bool(flags & IFF_UP and flags & IFF_RUNNING)))
    return out


# Whether the last real discovery fell back to the ioctls (primary addresses only); the wait and its refusal say so.
_seen = {"primary_only": False}
PRIMARY_ONLY = "only each interface's primary address is seen on this system"


def seen_note() -> str:
    """"" when every address is seen; else a clause for the wait line and the refusal (C3)."""
    return f" ({PRIMARY_ONLY})" if _seen["primary_only"] and _fake is None else ""


def _primary_only() -> list[tuple[str, str, int, bool]]:
    """The 1.47.0 discovery, kept as the fallback: one ioctl per name, the primary IPv4 address only."""
    _seen["primary_only"] = True
    out = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for _index, name in socket.if_nameindex():
            try:
                addr = _ioctl(s, SIOCGIFADDR, name)
                mask = _ioctl(s, SIOCGIFNETMASK, name)
                flags = struct.unpack("H", _ioctl(s, SIOCGIFFLAGS, name)[16:18])[0]
                prefix = ipaddress.IPv4Network(f"0.0.0.0/{socket.inet_ntoa(mask[20:24])}").prefixlen
            except (OSError, ValueError):
                # no IPv4 address (EADDRNOTAVAIL), gone since it was listed, or (C4) a netmask that is not
                # contiguous, which IPv4Network refuses: that interface is left out, never a crash
                continue
            out.append((name, socket.inet_ntoa(addr[20:24]), prefix, bool(flags & IFF_UP and flags & IFF_RUNNING)))
    return out


NETLINK_ROUTE, RTM_NEWADDR, RTM_GETADDR = 0, 20, 22
NLMSG_ERROR, NLMSG_DONE = 2, 3
NLM_F_REQUEST, NLM_F_DUMP = 0x1, 0x300
IFA_ADDRESS, IFA_LOCAL = 1, 2
_NLMSGHDR, _IFADDRMSG, _RTATTR = "=IHHII", "=BBBBI", "=HH"


def _netlink_addresses() -> list[tuple[int, str, int]]:
    """(interface index, IPv4 address, prefix length) for every IPv4 address, from one RTM_GETADDR dump."""
    with socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, NETLINK_ROUTE) as s:
        s.settimeout(5)
        s.bind((0, 0))
        hdr = struct.calcsize(_NLMSGHDR) + struct.calcsize(_IFADDRMSG)
        s.sendto(struct.pack(_NLMSGHDR, hdr, RTM_GETADDR, NLM_F_REQUEST | NLM_F_DUMP, 1, 0)
                 + struct.pack(_IFADDRMSG, socket.AF_INET, 0, 0, 0, 0), (0, 0))
        out: list[tuple[int, str, int]] = []
        while True:
            buf = s.recv(1 << 16)
            if not buf:
                # an empty read is no progress and no timeout, so the loop would spin forever: take it as
                # "netlink unavailable" and let the caller fall back to the primary-only ioctls
                raise OSError("netlink closed the address dump before it was done")
            got, done = parse_netlink(buf)
            out.extend(got)
            if done:
                return out


def parse_netlink(data: bytes) -> tuple[list[tuple[int, str, int]], bool]:
    """One recv of an RTM_GETADDR dump: ([(index, address, prefix length)], whether the dump is done). IFA_LOCAL
    is the address itself (IFA_ADDRESS is the peer's on a point-to-point link), so it is preferred. Raises
    OSError on a netlink error or a malformed message, which the caller takes as "netlink unavailable"."""
    out, off, nl = [], 0, struct.calcsize(_NLMSGHDR)
    while off + nl <= len(data):
        length, kind, _flags, _seq, _pid = struct.unpack_from(_NLMSGHDR, data, off)
        if length < nl or off + length > len(data):
            raise OSError("a malformed netlink message")
        if kind == NLMSG_DONE:
            return out, True
        if kind == NLMSG_ERROR:
            raise OSError("netlink refused the address dump")
        if kind == RTM_NEWADDR and length >= nl + struct.calcsize(_IFADDRMSG):
            family, prefix, _f, _scope, index = struct.unpack_from(_IFADDRMSG, data, off + nl)
            attrs, a = {}, off + nl + struct.calcsize(_IFADDRMSG)
            while a + 4 <= off + length:
                alen, atype = struct.unpack_from(_RTATTR, data, a)
                if alen < 4:
                    break
                attrs[atype] = data[a + 4:a + alen]
                a += (alen + 3) & ~3
            ip = attrs.get(IFA_LOCAL) or attrs.get(IFA_ADDRESS)
            if family == socket.AF_INET and ip and len(ip) >= 4 and 0 <= prefix <= 32:
                out.append((index, socket.inet_ntoa(ip[:4]), prefix))
        off += (length + 3) & ~3
    return out, False


def overlay_kind(name: str, addr: str) -> str | None:
    """"zerotier", "tailscale" or None (L14): which overlay `name` is, by its name and `addr`."""
    if name.startswith("zt"):
        return "zerotier"
    if name == "tailscale0" or (name.startswith("tailscale") and ipaddress.IPv4Address(addr) in TAILSCALE_NET):
        return "tailscale"
    return None


def overlays(ifaces: list | None = None) -> list[tuple[str, str, str, int, bool]]:
    """(kind, name, address, prefix length, up) for every ZeroTier or Tailscale interface (onboard.py detect)."""
    return [(k, n, a, p, u) for n, a, p, u in (interfaces() if ifaces is None else ifaces)
            for k in (overlay_kind(n, a),) if k]


def static_problem(addr: object) -> str | None:
    """Why `addr` is refused before any interface is looked at (contract 1), or None."""
    if not isinstance(addr, str):
        return "--listen takes one IPv4 address, e.g. 10.147.17.10"
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return f"--listen {addr!r} is refused: it takes one IPv4 address, e.g. 10.147.17.10"
    if ip.version == 6:
        return f"--listen {addr} is refused: IPv6 is not taken; give the interface's IPv4 address"
    if str(ip) != addr:
        return f"--listen {addr!r} is refused: write the address plainly, as {ip}"
    if ip.is_unspecified:
        return "--listen 0.0.0.0 is refused: it would listen on every interface; give the ZeroTier or Tailscale address"
    if ip.is_loopback and not (_fake is not None and _fake[1]):
        return (f"--listen {addr} is refused: it is a loopback address, and without --listen the console is on "
                f"127.0.0.1 already")
    if ip in TAILSCALE_NET:
        return None
    if ip.is_global:
        return (f"--listen {addr} is refused: it is a public address; only a ZeroTier address or a Tailscale "
                f"one (100.64.0.0/10) is taken")
    if ip.is_multicast or ip.is_reserved or ip.is_link_local:
        return f"--listen {addr} is refused: no ZeroTier or Tailscale interface has an address like it"
    return None


def holders(addr: str, ifaces: list) -> list[tuple[str, str, int, bool]]:
    return [i for i in ifaces if i[1] == addr]


def check(addr: str, ifaces: list | None = None) -> tuple[str, int, bool] | None:
    """Contract 1, now: the (interface name, prefix length, up) that may carry `addr`; None when no interface
    holds it yet (L16 waits for it). Raises ListenError for an address refused by name, off Linux, or held
    by an interface that is not ZeroTier or Tailscale (refused at once, never waited for)."""
    if _fake is None and not sys.platform.startswith("linux"):
        raise ListenError(NOT_LINUX)
    why = static_problem(addr)
    if why:
        raise ListenError(why)
    found = holders(addr, interfaces() if ifaces is None else ifaces)
    # 1.47 (S3): every holder must be an overlay. An address that is ZeroTier's and also an alias on eth0 (or a
    # bridge) would be reached through that interface too, so it is refused, naming the other interface.
    others = sorted({name for name, a, _p, _u in found if not overlay_kind(name, a)})
    overlay = sorted({name for name, a, _p, _u in found if overlay_kind(name, a)})
    if others and overlay:
        raise ListenError(f"--listen {addr} is refused: it is on {', '.join(others)} as well as "
                          f"{', '.join(overlay)}; it must be on a ZeroTier or Tailscale interface only")
    if others:
        raise ListenError(f"--listen {addr} is refused: it is on {', '.join(others)}, "
                          f"not a ZeroTier (zt…) or Tailscale (tailscale0) interface")
    for name, a, prefix, up in found:
        return name, prefix, up
    return None


def problem(addr: object) -> str | None:
    """Why `addr` cannot be listened on right now (refused, or on no interface yet), or None."""
    try:
        got = check(addr)  # type: ignore[arg-type]   (static_problem names a non-string)
    except ListenError as e:
        return str(e)
    return None if got else f"--listen {addr}: no ZeroTier or Tailscale interface holds it now"


def waiting_line(addr: str) -> str:
    return f"overture: waiting for {addr} on a ZeroTier or Tailscale interface (up to 2 minutes){seen_note()}"


def wait(addr: str, say: Callable[[str], None], sleep: Callable[[float], None] = time.sleep,
         clock: Callable[[], float] = time.monotonic, seconds: float = WAIT_SECONDS,
         every: float = POLL_SECONDS) -> tuple[str, int, bool]:
    """L16: `check` until an allowed interface holds `addr`, every `every` seconds for up to `seconds`, saying
    exactly one line (`waiting_line`) if it is not there at first. ListenError on a refusal (at once, also one
    that appears mid-wait) or when the time is up: the caller exits 1 and the service restarts it."""
    got = check(addr)
    if got:
        return got
    say(waiting_line(addr))
    end = clock() + seconds
    while clock() < end:
        sleep(every)
        got = check(addr)
        if got:
            return got
    raise ListenError(f"--listen {addr}: no ZeroTier or Tailscale interface held it within 2 minutes; is "
                      f"ZeroTier (or Tailscale) running and joined to its network?{seen_note()} Exiting so the "
                      f"service tries again")


def overlap_warnings(addr: str, iface: tuple[str, int, bool], ifaces: list | None = None) -> list[str]:
    """L17: one warning per OTHER interface whose IPv4 network overlaps the listen network (down ones too,
    marked), naming the interface and both networks. A Docker bridge on the ZeroTier range may take its route."""
    name, prefix, _up = iface
    mine = ipaddress.IPv4Network(f"{addr}/{prefix}", strict=False)
    kind = "ZeroTier" if overlay_kind(name, addr) == "zerotier" else "Tailscale"
    fix = ("move the ZeroTier network to another range (my.zerotier.com), or Docker's default-address-pools "
           "(/etc/docker/daemon.json)" if kind == "ZeroTier" else
           "move Docker's default-address-pools (/etc/docker/daemon.json) off 100.64.0.0/10")
    out = []
    for n, a, p, up in sorted(interfaces() if ifaces is None else ifaces):
        if n == name:
            continue
        theirs = ipaddress.IPv4Network(f"{a}/{p}", strict=False)
        if theirs.overlaps(mine):
            out.append(f"overture: warning: {n}{'' if up else ' (down)'} is on {theirs}, which overlaps the "
                       f"{kind} network {mine} of {name}; it may shadow the {kind} route. To be safe, {fix}")
    return out


def accept(addr: str, say: Callable[[str], None]) -> tuple[str, int, bool]:
    """What a starting console runs: wait for `addr` (L16), then say every overlap warning (L17). Returns the
    interface; raises ListenError (exit 1)."""
    got = wait(addr, say)
    for line in overlap_warnings(addr, got):
        say(line)
    return got
