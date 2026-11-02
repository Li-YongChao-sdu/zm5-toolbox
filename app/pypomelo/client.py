"""pomelo TCP/TLS 客户端。

对应 AS: org.idream.pomelo.Pomelo + PomeloEvent + Request + LocalData

用法:
    c = PomeloClient()
    c.on("connector.entryHandler.entry", lambda body: print("push", body))
    c.connect("host.com", 3010, user={"uid": 123})
    c.request("route.to.server", {"a": 1}, lambda body: print("resp", body))
    ...
    c.disconnect()

说明:
- 传输层走 TLS(对应 AS 的 TLSSocket, trustAllCertificates=True);
- 握手 -> 等服务端 sys 配置 -> 回 ACK -> 心跳;
- 请求(request)带自增 id, 响应按 id 回调; 通知(notify)不带 id;
- 服务端下行推送(push)按 route 分发到 on() 注册的回调。
"""

import hashlib
import json
import socket
import ssl
import threading
import time

from . import package
from .routedic import Routedic
from .protodef import Protobuf
from .message import MessageCodec


class PomeloClient:
    CLIENT_VERSION = "0.1.6b"
    CLIENT_TYPE = "pomelo-flash-tcp"
    POMELO_VERSION = "0.7.x"

    def __init__(self, proto_cache_path: str | None = None) -> None:
        self.routedic = Routedic()
        self.protobuf = Protobuf()
        self.codec = MessageCodec(self.routedic, self.protobuf)
        self._proto_cache_path = proto_cache_path

        self._sock: ssl.SSLSocket | None = None
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._req_id = 0
        self._pending: dict[int, dict] = {}      # id -> {"route":..., "callback":...}
        self._push_handlers: dict[str, list] = {}
        self._handshake_cb = None
        self._close_cb = None
        self._kicked_cb = None

        self.heartbeat = 0.0
        self._hb_timer: threading.Timer | None = None
        self._reader: threading.Thread | None = None
        self._running = False

    # ------------------------------------------------------------------ connect
    def connect(self, host: str, port: int, user: dict | None = None,
                handshake_cb=None, timeout: float = 8.0,
                local_protos: dict | None = None) -> None:
        """建立 TLS 连接并发起握手。

        user:          握手 sys.user 字段内容
        handshake_cb:  握手完成回调(参数为服务端握手 JSON)
        local_protos:  本地缓存的 protos {client, server}; 提供时计算 protoVersion
        """
        self._handshake_cb = handshake_cb

        # TLS: 对应 AS trustAllCertificates / ignoreCommonNameMismatch
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        raw = socket.create_connection((host, port), timeout=timeout)
        self._sock = ctx.wrap_socket(raw, server_hostname=host)
        self._sock.settimeout(None)

        # 本地 protos -> protoVersion (对应 AS: MD5(client + server))
        sys_info = {
            "version": self.CLIENT_VERSION,
            "type": self.CLIENT_TYPE,
            "pomelo_version": self.POMELO_VERSION,
        }
        protos = local_protos
        if protos is None and self._proto_cache_path:
            try:
                with open(self._proto_cache_path, "r", encoding="utf-8") as f:
                    protos = json.load(f)
            except (OSError, ValueError):
                protos = None
        if protos:
            sys_info["protoVersion"] = self._proto_version(protos)
            self.protobuf.init(protos)

        info = {"sys": sys_info, "user": user or {}}
        body = json.dumps(info, separators=(",", ":")).encode("utf-8")
        self._send_package(package.TYPE_HANDSHAKE, body)

        self._running = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    @staticmethod
    def _proto_version(protos: dict) -> str:
        client = json.dumps(protos.get("client") or {}, sort_keys=True)
        server = json.dumps(protos.get("server") or {}, sort_keys=True)
        return hashlib.md5((client + server).encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------ public api
    def on(self, route: str, callback) -> None:
        """注册推送(下行 notify)回调。"""
        self._push_handlers.setdefault(route, []).append(callback)

    def set_close_callback(self, cb) -> None:
        self._close_cb = cb

    def set_kicked_callback(self, cb) -> None:
        self._kicked_cb = cb

    def request(self, route: str, data, callback=None) -> None:
        """发请求; callback(resp_body)。callback 为空则按 notify 发。"""
        if callback is None:
            self.notify(route, data)
            return
        with self._lock:
            self._req_id += 1
            rid = self._req_id
            self._pending[rid] = {"route": route, "callback": callback}
        payload = self.codec.encode(rid, route, data or {})
        self._send_package(package.TYPE_DATA, payload)

    def notify(self, route: str, data) -> None:
        payload = self.codec.encode(0, route, data or {})
        self._send_package(package.TYPE_DATA, payload)

    def disconnect(self) -> None:
        self._running = False
        self._cancel_heartbeat()
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass
        self._sock = None

    # ------------------------------------------------------------------ send
    def _send_package(self, pkg_type: int, body: bytes | None = None) -> None:
        packet = package.encode(pkg_type, body)
        with self._send_lock:
            sock = self._sock
            if sock is None:
                return
            sock.sendall(packet)

    # ------------------------------------------------------------------ recv loop
    def _read_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("connection closed")
            buf += chunk
        return bytes(buf)

    def _read_loop(self) -> None:
        try:
            while self._running:
                header = self._read_exact(4)
                pkg_type, length = package.decode_header(header)
                body = self._read_exact(length) if length else b""
                self._handle_package(pkg_type, body)
        except (OSError, ConnectionError):
            pass
        finally:
            self._running = False
            self._cancel_heartbeat()
            if self._close_cb:
                try:
                    self._close_cb()
                except Exception:
                    pass

    # ------------------------------------------------------------------ dispatch
    def _handle_package(self, pkg_type: int, body: bytes) -> None:
        if pkg_type == package.TYPE_HANDSHAKE:
            self._on_handshake(body)
        elif pkg_type == package.TYPE_HANDSHAKE_ACK:
            pass
        elif pkg_type == package.TYPE_HEARTBEAT:
            self._schedule_heartbeat()
        elif pkg_type == package.TYPE_DATA:
            self._on_data(body)
        elif pkg_type == package.TYPE_KICK:
            if self._kicked_cb:
                try:
                    self._kicked_cb()
                except Exception:
                    pass
            self.disconnect()

    def _on_handshake(self, body: bytes) -> None:
        resp = json.loads(body.decode("utf-8"))
        if resp.get("code") == 200 and resp.get("sys"):
            sysconf = resp["sys"]
            self.routedic.init(sysconf.get("dict"))
            protos = sysconf.get("protos")
            if protos:
                self.protobuf.init(protos)
                if self._proto_cache_path:
                    try:
                        with open(self._proto_cache_path, "w", encoding="utf-8") as f:
                            json.dump(protos, f)
                    except OSError:
                        pass
            self.heartbeat = float(sysconf.get("heartbeat") or 0)
            # 握手成功 -> 回 ACK
            self._send_package(package.TYPE_HANDSHAKE_ACK)
            self._schedule_heartbeat()
        if self._handshake_cb:
            try:
                self._handshake_cb(resp)
            except Exception:
                pass

    def _on_data(self, body: bytes) -> None:
        pending_routes = {rid: item["route"] for rid, item in self._pending.items()}
        msg = self.codec.decode(body, pending_routes)
        rid = msg["id"]
        if rid:
            item = self._pending.pop(rid, None)
            if item:
                try:
                    item["callback"](msg["body"])
                except Exception:
                    pass
        else:
            route = msg["route"]
            for cb in self._push_handlers.get(route, []):
                try:
                    cb(msg["body"])
                except Exception:
                    pass

    # ------------------------------------------------------------------ heartbeat
    def _cancel_heartbeat(self) -> None:
        if self._hb_timer:
            self._hb_timer.cancel()
            self._hb_timer = None

    def _schedule_heartbeat(self) -> None:
        """收到服务端心跳后, 定时回发心跳(对应 AS: setTimeout(beat, hb*1000))。"""
        if not self.heartbeat:
            return
        self._cancel_heartbeat()
        self._hb_timer = threading.Timer(self.heartbeat, self._beat)
        self._hb_timer.daemon = True
        self._hb_timer.start()

    def _beat(self) -> None:
        if not self._running:
            return
        try:
            self._send_package(package.TYPE_HEARTBEAT)
        except OSError:
            return
        # 发完后继续等服务端下一个心跳; 这里也兜底再排一次
        self._schedule_heartbeat()
