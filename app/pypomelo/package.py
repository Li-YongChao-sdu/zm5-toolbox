"""pomelo 包(包头)编解码。

对应 AS: org.idream.pomelo.Package

包格式(二进制, 大端):
    [1 字节 type][3 字节 body 长度(大端)][body ...]

type:
    1 = HANDSHAKE       握手(客户端发 / 服务端回)
    2 = HANDSHAKE_ACK    握手应答(客户端发, 空 body)
    3 = HEARTBEAT        心跳(双向, 空 body)
    4 = DATA             数据(里面是 Message)
    5 = KICK             被踢下线(服务端发)
"""

TYPE_HANDSHAKE = 1
TYPE_HANDSHAKE_ACK = 2
TYPE_HEARTBEAT = 3
TYPE_DATA = 4
TYPE_KICK = 5


def encode(pkg_type: int, body: bytes | bytearray | None = None) -> bytes:
    """把 type + body 编码成 4 字节包头 + 包体。"""
    body = bytes(body) if body else b""
    length = len(body)
    if length > 0xFFFFFF:
        raise ValueError("pomelo package body too large: %d" % length)
    header = bytes([
        pkg_type & 0xFF,
        (length >> 16) & 0xFF,
        (length >> 8) & 0xFF,
        length & 0xFF,
    ])
    return header + body


def decode_header(header: bytes) -> tuple[int, int]:
    """从 4 字节包头解析 (type, length)。"""
    if len(header) < 4:
        raise ValueError("need 4 header bytes, got %d" % len(header))
    pkg_type = header[0]
    length = (header[1] << 16) | (header[2] << 8) | header[3]
    return pkg_type, length
