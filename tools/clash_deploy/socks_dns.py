#!/usr/bin/env python3
"""经clash socks5隧道(7890)裸TCP查DNS — 绕开DoH域名被墙/被路由直连的问题"""
import socket, struct, sys, random

PROXY = ("127.0.0.1", 7890)

def socks5_connect(dest_ip, dest_port):
    s = socket.create_connection(PROXY, timeout=25)
    s.settimeout(25)
    s.sendall(b"\x05\x01\x00")                      # greeting: no-auth
    r = s.recv(2)
    assert r == b"\x05\x00", f"socks hello fail: {r!r}"
    s.sendall(b"\x05\x01\x00\x01" + socket.inet_aton(dest_ip) + struct.pack(">H", dest_port))
    r = s.recv(4)
    assert r[:2] == b"\x05\x00", f"socks connect fail: {r!r}"
    s.recv(2 + struct.unpack(">H", s.recv(2)[:2])[0] if False else 6)  # bnd(4)+port(2), 粗略
    return s

def build_query(name):
    tid = random.randint(0, 65535)
    q = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    for lbl in name.split("."):
        q += bytes([len(lbl)]) + lbl.encode()
    q += b"\x00" + struct.pack(">HH", 1, 1)          # A, IN
    return tid, q

def tcp_dns(resolver_ip, name):
    tid, q = build_query(name)
    s = socks5_connect(resolver_ip, 53)
    s.sendall(struct.pack(">H", len(q)) + q)
    ln = s.recv(2)
    need = struct.unpack(">H", ln)[0]
    buf = b""
    while len(buf) < need:
        c = s.recv(need - len(buf))
        if not c:
            break
        buf += c
    s.close()
    rcode = buf[3] & 0xF
    # 跳过question
    i = 12
    while buf[i] != 0:
        i += buf[i] + 1
    i += 5
    ips = []
    an = struct.unpack(">H", buf[6:8])[0]
    for _ in range(an):
        while True:                                   # name可能是压缩指针
            l = buf[i]
            if l & 0xC0 == 0xC0:
                i += 2; break
            if l == 0:
                i += 1; break
            i += l + 1
        t, c_, ttl, dl = struct.unpack(">HHIH", buf[i:i+10])
        i += 10
        if t == 1 and dl == 4:
            ips.append(socket.inet_ntoa(buf[i:i+4]))
        i += dl
    return rcode, ips

DOMAINS = ["google.com", "a-node.ddqo.blog", "b-node.ddqo.blog"]
RESOLVERS = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
for d in DOMAINS:
    for r in RESOLVERS:
        try:
            rc, ips = tcp_dns(r, d)
            print(f"{d:20s} @{r}: rcode={rc} ips={ips}")
        except Exception as e:
            print(f"{d:20s} @{r}: ERR {type(e).__name__}: {e}")
    print()
