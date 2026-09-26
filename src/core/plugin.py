"""
插件基类与管理器。

插件铁律（每个插件作者必须知道）：
- 所有回调都在 pyCraft 的单一网络线程串行执行：回调里禁止 sleep、禁止耗时计算，
  否则收发包全部卡死，约 30 秒后被服务器踢出。
- 回调里禁止调用 bot.stop() / connection.disconnect()（网络线程内断连有重入风险）；
  想停止程序只能调 bot.request_stop()。
- 在 setup() 里用 self.on(...) 订阅事件、self.bot.commands 注册指令；
  插件注销时订阅会自动全部退订，无需手动清理。
"""
from __future__ import annotations

from typing import Callable, TYPE_CHECKING

from src.core.logger import get_logger

if TYPE_CHECKING:
    # 仅类型检查用，运行时不导入——否则与 src.core.bot 循环引用。
    from src.core.bot import Bot

logger = get_logger(__name__)


class Plugin:
    """插件基类。子类覆写 setup()，可选覆写 teardown()。"""
    name: str = "plugin"

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._tokens: list[Callable[[], None]] = []

    def on(self, event_type: type, handler: Callable) -> None:
        """订阅事件并记账，插件注销时自动退订。"""
        self._tokens.append(self.bot.events.on(event_type, handler))

    def setup(self) -> None:
        """子类覆写：注册指令、订阅事件。"""

    def teardown(self) -> None:
        """子类可选覆写：释放文件句柄等外部资源。"""

    def _unbind(self) -> None:
        """管理器专用：退订全部事件，再执行 teardown。"""
        for token in self._tokens:
            token()
        self._tokens.clear()
        self.teardown()


class PluginManager:
    """按注册顺序管理插件的启停。"可开关"就一个参数：enabled=False。"""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._plugins: list[Plugin] = []

    def register(self, plugin_cls: type[Plugin], enabled: bool = True) -> Plugin | None:
        """只实例化登记，不启动；enabled=False 直接跳过。"""
        if not enabled:
            return None
        plugin = plugin_cls(self.bot)
        self._plugins.append(plugin)
        return plugin

    def setup_all(self) -> None:
        """connect() 之前调用，保证一个事件都不漏。单个插件失败不影响其余。"""
        for plugin in self._plugins:
            try:
                plugin.setup()
            except Exception:
                logger.error("%s setup 失败", plugin.name, exc_info=True)

    def teardown_all(self) -> None:
        """按注册的逆序注销全部插件。"""
        for plugin in reversed(self._plugins):
            try:
                plugin._unbind()
            except Exception:
                logger.error("%s teardown 异常", plugin.name, exc_info=True)
        self._plugins.clear()
