"""pomelo 消息(包体)编解码。

对应 AS: org.idream.pomelo.Message

消息字节流(在 TYPE_DATA=4 的包体里):
    flags(1字节)
    [id varint]              # 仅 request(0)/response(2)
    [route]                  # request/notify/push 才有; response 用请求表里的 route
    body(protobuf 或 JSON)

flags 位:
    bit 0 (0x01)      1 = route 是数字码(2字节大端), 0 = route 字符串
    bit 1-3 (0x0E>>1) 消息类型: 0=request 1=notify 2=response 3=push
    bit 4 (0x10)      1 = body 经过 raw-deflate 压缩

压缩: 仅 JSON body 且原始长度 > 1024 时尝试 raw-deflate, 压缩后更小才启用。
"""

import json
import zlib

from . import package
from .routedic import Routedic
from .protodef import Protobuf

MSG_TYPE_REQUEST = 0
MSG_TYPE_NOTIFY = 1
MSG_TYPE_RESPONSE = 2
MSG_TYPE_PUSH = 3

_FLAG_ROUTE_CODE = 0x01
_FLAG_GZIP = 0x10
_GZIP_THRESHOLD = 1024


class MessageCodec:
    def __init__(self, routedic: Routedic, protobuf: Protobuf) -> None:
        self.routedic = routedic
        self.protobuf = protobuf

    # ---------- varint (message id) ----------

    @staticmethod
    def _write_varint(value: int) -> bytes:
        out = bytearray()
        while True:
            b = value & 0x7F
            value >>= 7
            if value:
                out.append(b | 0x80)
            else:
                out.append(b)
                return bytes(out)

    @staticmethod
    def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
        result = 0
        shift = 0
        while True:
            b = buf[pos]
            pos += 1
            result |= (b & 0x7F) << shift
            if b < 0x80:
                return result, pos
            shift += 7

    # ---------- encode (client -> server) ----------

    def encode(self, msg_id: int, route: str, data) -> bytes:
        # request(id!=0) -> type 0; notify(id==0) -> type 1
        msg_type = MSG_TYPE_REQUEST if msg_id else MSG_TYPE_NOTIFY

        # 1) body: 先尝试 protobuf, 失败则 JSON
        body = self.protobuf.encode(route, data)
        gzip_flag = 0
        if body is None:
            raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
            if len(raw) > _GZIP_THRESHOLD:
                co = zlib.compressobj(9, zlib.DEFLATED, -15)  # raw deflate
                compressed = co.compress(raw) + co.flush()
                if len(compressed) < len(raw):
                    body = compressed
                    gzip_flag = _FLAG_GZIP
                else:
                    body = raw
            else:
                body = raw

        # 2) route: 能压缩成数字码就压, 否则字符串
        code = self.routedic.get_id(route)
        route_is_code = code is not None

        flags = (msg_type << 1) | (_FLAG_ROUTE_CODE if route_is_code else 0) | gzip_flag
        out = bytearray([flags])

        if msg_id:
            out += self._write_varint(msg_id)

        if route_is_code:
            out += bytes([(code >> 8) & 0xFF, code & 0xFF])
        else:
            route_bytes = route.encode("utf-8")
            out.append(len(route_bytes) & 0xFF)
            out += route_bytes

        out += body
        return bytes(out)

    # ---------- decode (server -> client) ----------

    def decode(self, buf: bytes, pending_routes: dict[int, str]) -> dict:
        """pending_routes: {msg_id: route} 用于 response 反查。"""
        pos = 0
        flags = buf[pos]; pos += 1
        route_compressed = bool(flags & _FLAG_ROUTE_CODE)
        msg_type = (flags >> 1) & 0x07
        gzip_flag = bool((flags >> 4) & 0x01)

        msg_id = 0
        if msg_type in (MSG_TYPE_REQUEST, MSG_TYPE_RESPONSE):
            msg_id, pos = self._read_varint(buf, pos)

        # route
        route = None
        if msg_type in (MSG_TYPE_REQUEST, MSG_TYPE_NOTIFY, MSG_TYPE_PUSH):
            if route_compressed:
                code = (buf[pos] << 8) | buf[pos + 1]
                pos += 2
                route = self.routedic.get_name(code)
            else:
                rlen = buf[pos]; pos += 1
                route = buf[pos:pos + rlen].decode("utf-8")
                pos += rlen
        elif msg_type == MSG_TYPE_RESPONSE:
            route = pending_routes.get(msg_id)

        # push 且 route 仍是数字码(字典里没有) -> 原样保留
        if not msg_id and not isinstance(route, str):
            route = self.routedic.get_name(route)

        body = buf[pos:]
        if gzip_flag:
            d = zlib.decompressobj(-15)  # raw deflate
            body = d.decompress(body) + d.flush()

        # 先尝试 protobuf, 失败回退 JSON
        decoded = self.protobuf.decode(route, body) if isinstance(route, str) else None
        if decoded is None:
            decoded = json.loads(body.decode("utf-8")) if body else {}

        return {
            "id": msg_id,
            "type": msg_type,
            "route": route,
            "body": decoded,
        }
