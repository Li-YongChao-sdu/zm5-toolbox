"""pomelo 自定义 protobuf 编解码。

对应 AS: org.idream.pomelo.Protobuf

注意: 这不是标准 .proto, 而是 pomelo 0.7 的一套轻量 varint 协议, 字段定义
来自握手时服务端下发的 sys.protos, 结构形如:

    {
      "client": {                      # 客户端发往服务端的消息(按 route)
        "connector.entryHandler.entry": {
          "uid":  {"option":"required","type":"int32","tag":1},
          "name": {"option":"optional","type":"string","tag":2}
        },
        "message SomeMessage": { ... } # 嵌套消息定义
      },
      "server": { ... }                # 服务端下行的消息(按 route)
    }

wire type:
    uInt32/sInt32/int32 = 0 (varint)
    double              = 1
    string/message       = 2
    float               = 5
"""

import struct

# type -> wire type
_WIRE = {
    "uInt32": 0,
    "sInt32": 0,
    "int32": 0,
    "double": 1,
    "string": 2,
    "message": 2,
    "float": 5,
}

_SIMPLE = {"uInt32", "sInt32", "int32", "uInt64", "sInt64", "float", "double"}


def _wire_type(t: str) -> int:
    return _WIRE.get(t, 2)


# ---------- varint ----------

def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    """标准 LEB128 无符号 varint。返回 (value, new_pos)。"""
    result = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated varint")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if b < 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def _write_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("varint cannot be negative: %d" % value)
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _encode_sint(value: int) -> int:
    # AS: n<0 ? abs(n)*2-1 : n*2   (标准 zigzag)
    n = int(value)
    return (-n * 2 - 1) if n < 0 else (n * 2)


def _decode_sint(value: int) -> int:
    # AS: odd -> -(n+1)/2, even -> n/2
    return -((value + 1) // 2) if (value & 1) else (value // 2)


class Protobuf:
    def __init__(self) -> None:
        self._clients: dict = {}
        self._servers: dict = {}
        # 全局 message 类型名 -> schema, 用于嵌套消息解析
        self._messages: dict[str, dict] = {}

    # ---------- init ----------

    def init(self, protos: dict | None) -> None:
        protos = protos or {}
        self._clients = protos.get("client") or {}
        self._servers = protos.get("server") or {}
        self._messages = {}
        for container in (self._clients, self._servers):
            for name, schema in container.items():
                if isinstance(schema, dict):
                    self._register_schema(name, schema)

    def _register_schema(self, name: str, schema: dict) -> None:
        # 形如 "message Foo" 的键登记为嵌套消息; 普通 route 也顺带登记其字段
        base = name.split(" ", 1)[-1]
        self._messages[base] = schema
        self._messages["message " + base] = schema
        # 构造 __tags: tag -> 字段名 (AS 运行时直接用 schema.__tags[tag])
        tags = {}
        for fname, fdef in schema.items():
            if isinstance(fdef, dict) and "tag" in fdef:
                tags[fdef["tag"]] = fname
        schema.setdefault("__tags", tags)

    def _lookup_message(self, schema: dict, type_name: str) -> dict | None:
        # AS: schema.__messages[type] || container["message " + type]
        # 这里同时兼容字段 type 写成 "BagItem" 或 "message BagItem"
        base = type_name.split(" ", 1)[-1]
        msgs = schema.get("__messages") if isinstance(schema, dict) else None
        for key in (type_name, base, "message " + base):
            if msgs and key in msgs:
                return msgs[key]
            if key in self._messages:
                return self._messages[key]
        return None

    # ---------- public ----------

    def encode(self, route: str, data: dict) -> bytes | None:
        schema = self._clients.get(route)
        if not isinstance(schema, dict):
            return None
        return self._encode_msg(schema, data)

    def decode(self, route: str, buf: bytes) -> dict | None:
        schema = self._servers.get(route)
        if not isinstance(schema, dict):
            return None
        return self._decode_msg(schema, buf)

    # ---------- message ----------

    def _encode_msg(self, schema: dict, data: dict) -> bytes:
        out = bytearray()
        for fname, fdef in schema.items():
            if fname.startswith("__") or not isinstance(fdef, dict):
                continue
            if fname not in data or data[fname] is None:
                continue
            option = fdef.get("option")
            ftype = fdef["type"]
            tag = fdef["tag"]
            value = data[fname]
            if option in ("optional", "required"):
                out += _write_varint((tag << 3) | _wire_type(ftype))
                self._encode_prop(out, schema, ftype, value)
            elif option == "repeated":
                if isinstance(value, list) and len(value) > 0:
                    self._encode_array(out, schema, ftype, tag, value)
        return bytes(out)

    def _decode_msg(self, schema: dict, buf: bytes) -> dict:
        result = {}
        tags = schema.get("__tags", {})
        pos = 0
        while pos < len(buf):
            head, pos = _read_varint(buf, pos)
            tag = head >> 3
            fname = tags.get(tag)
            if fname is None:
                # 未知 tag, 放弃解析整条 (AS 行为: String(undefined) -> "undefined")
                break
            fdef = schema[fname]
            option = fdef.get("option")
            ftype = fdef["type"]
            if option in ("optional", "required"):
                val, pos = self._decode_prop(buf, pos, schema, ftype)
                result[fname] = val
            elif option == "repeated":
                result.setdefault(fname, [])
                pos = self._decode_array(buf, pos, schema, ftype, result[fname])
        return result

    # ---------- array ----------

    def _encode_array(self, out: bytearray, schema: dict,
                      ftype: str, tag: int, arr: list) -> None:
        if ftype in _SIMPLE:
            # packed: 单个 tag + varint 个数 + 连续值
            out += _write_varint((tag << 3) | _wire_type(ftype))
            out += _write_varint(len(arr))
            for item in arr:
                self._encode_prop(out, schema, ftype, item)
        else:
            # 非 packed: 每个元素一个 tag
            for item in arr:
                out += _write_varint((tag << 3) | _wire_type(ftype))
                self._encode_prop(out, schema, ftype, item)

    def _decode_array(self, buf: bytes, pos: int, schema: dict,
                      ftype: str, out_list: list) -> int:
        if ftype in _SIMPLE:
            count, pos = _read_varint(buf, pos)
            for _ in range(count):
                val, pos = self._decode_prop(buf, pos, schema, ftype)
                out_list.append(val)
        else:
            val, pos = self._decode_prop(buf, pos, schema, ftype)
            out_list.append(val)
        return pos

    # ---------- scalar ----------

    def _encode_prop(self, out: bytearray, schema: dict,
                     ftype: str, value) -> None:
        if ftype == "uInt32":
            out += _write_varint(int(value))
        elif ftype in ("int32", "sInt32"):
            out += _write_varint(_encode_sint(int(value)))
        elif ftype == "float":
            out += struct.pack("<f", float(value))
        elif ftype == "double":
            out += struct.pack("<d", float(value))
        elif ftype == "string":
            s = "" if value is None else str(value)
            raw = s.encode("utf-8")
            out += _write_varint(len(raw))
            out += raw
        else:
            # 嵌套 message
            sub = self._lookup_message(schema, ftype)
            if sub is None:
                raise ValueError("unknown message type: %s" % ftype)
            body = self._encode_msg(sub, value or {})
            out += _write_varint(len(body))
            out += body

    def _decode_prop(self, buf: bytes, pos: int, schema: dict, ftype: str):
        """返回 (value, new_pos)。"""
        if ftype == "uInt32":
            v, pos = _read_varint(buf, pos)
            return v, pos
        if ftype in ("int32", "sInt32"):
            v, pos = _read_varint(buf, pos)
            return _decode_sint(v), pos
        if ftype == "float":
            return struct.unpack_from("<f", buf, pos)[0], pos + 4
        if ftype == "double":
            return struct.unpack_from("<d", buf, pos)[0], pos + 8
        if ftype == "string":
            length, pos = _read_varint(buf, pos)
            return buf[pos:pos + length].decode("utf-8"), pos + length
        # 嵌套 message
        sub = self._lookup_message(schema, ftype)
        if sub is None:
            raise ValueError("unknown message type: %s" % ftype)
        length, pos = _read_varint(buf, pos)
        if not length:
            return False, pos
        return self._decode_msg(sub, buf[pos:pos + length]), pos + length
