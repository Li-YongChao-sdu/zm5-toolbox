"""路由字典。

对应 AS: org.idream.pomelo.Routedic

握手时服务端下发 sys.dict, 形如 { "routeString": numericCode, ... }。
客户端把 route 字符串编码成 2 字节数字码(省流量);
服务端下行推送时也可能只给数字码, 需要反查回字符串。
"""


class Routedic:
    def __init__(self) -> None:
        self._ids: dict[str, int] = {}      # route -> code
        self._names: dict[int, str] = {}    # code -> route

    def init(self, dict_obj: dict | None) -> None:
        """dict_obj: { "connector.entryHandler.entry": 1, ... }"""
        self._ids = {}
        self._names = {}
        if not dict_obj:
            return
        for name, code in dict_obj.items():
            self._ids[name] = code
            self._names[code] = name

    def get_id(self, route: str) -> int | None:
        """route 字符串 -> 数字码; 不在字典里返回 None。"""
        return self._ids.get(route)

    def get_name(self, code: int) -> str | int:
        """数字码 -> route 字符串; 不在字典里原样返回 code。"""
        return self._names.get(code, code)
