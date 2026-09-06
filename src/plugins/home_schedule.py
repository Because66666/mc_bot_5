"""
插件：家园时间表——按时间表自动 /home 到正确的地址。

维护时间表只改本文件顶部的 HOME_POINTS / HOME_SCHEDULE：
1. HOME_POINTS 登记家园点：/home 指令用的服务器端名字 → 中文显示名（用于日志）；
2. HOME_SCHEDULE 加一行 (起始小时, 家园点名)，按起始小时升序排列。
   查表规则：取"起始小时 <= 当前小时"的最后一条；比第一条还早的小时回绕到最后一条。
   例如 [(0, "new"), (18, "base")] 表示 0-17 点在 new，18 点起在 base。

工作方式：后台线程每 CHECK_INTERVAL 秒查一次表，目标家园点变化且已连接时
自动发送 /home <名字>；重新进入游戏世界（JoinedGame）后重发一次。
线程是本插件自开的（README 铁律：耗时/阻塞任务不能放在网络线程回调里）。
"""
import threading
import time

from src.core.events import JoinedGame, WorldChanged
from src.core.plugin import Plugin

# ---------------------------------------------------------------------------
# 家园点注册表与时间表（日常维护只改这里）
# ---------------------------------------------------------------------------

#: /home 指令用的服务器端家园点名字 → 中文显示名
HOME_POINTS: dict[str, str] = {
    "new": "云岫-外交公馆",
}

#: 时间表：(起始小时[0-23], 家园点名)，按起始小时升序。
#: 目前默认 24 小时都是 new（云岫-外交公馆）。
HOME_SCHEDULE: list[tuple[int, str]] = [
    (0, "new"),
    # (18, "base"),  # 示例：18 点起切到 base（记得先在 HOME_POINTS 登记）
]

#: 查表间隔（秒）。
CHECK_INTERVAL = 60.0


class HomeSchedulePlugin(Plugin):
    name = "home_schedule"

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # 最近一次已发送的家园点；None 表示连入后需要发一次
        self._last_sent: str | None = None
        self._schedule = sorted(HOME_SCHEDULE)

    def setup(self) -> None:
        self.on(JoinedGame, self._on_joined) # 加入游戏时自动传送
        self.on(WorldChanged, self._on_joined) # 死亡后自动传送
        self._thread = threading.Thread(target=self._run,
                                        name=f"{self.name}-timer", daemon=True)
        self._thread.start()

    def teardown(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    # --- 时间表逻辑 ---

    def _current_target(self, hour: int) -> str | None:
        """按当前小时查时间表，返回家园点名；表为空返回 None。"""
        if not self._schedule:
            return None
        chosen = self._schedule[-1][1]  # 早于第一条起始时间 → 回绕到最后一条
        for start, name in self._schedule:
            if hour >= start:
                chosen = name
            else:
                break
        return chosen

    # --- 后台线程 ---

    def _run(self) -> None:
        while not self._stop.wait(CHECK_INTERVAL):
            try:
                self._tick()
            except Exception as e:
                print(f"[home] 时间表检查出错: {e}")

    def _tick(self) -> None:
        target = self._current_target(time.localtime().tm_hour)
        if target is None or target == self._last_sent:
            return
        if not self.bot.state.connected:
            return
        label = HOME_POINTS.get(target, target)
        # 发送失败（未连接等）不更新 _last_sent，下个周期自动重试
        if self.bot.send_server_command(f"home {target}"):
            self._last_sent = target
            print(f"[home] 按时间表前往 {label} (/home {target})")

    # --- 事件回调（网络线程） ---

    def _on_joined(self, event: JoinedGame) -> None:
        # 重新进入游戏世界后强制重发一次，保证位置符合时间表
        self._last_sent = None
