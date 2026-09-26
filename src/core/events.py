"""
事件总线与事件定义。

bridge 把协议包翻译成这里定义的事件，经 EventBus 同步分发给插件和指令系统。

铁律：所有回调都在 pyCraft 的单一网络线程串行执行——
- 回调里禁止 sleep / 重活，否则收发包卡死被服务器踢；
- 单线程同步分发，无需任何锁。
"""
from dataclasses import dataclass, field
from typing import Callable
from uuid import UUID

from src.core.logger import get_logger

logger = get_logger(__name__)


class EventBus:
    """同步事件总线：on / emit / off，全部心智就这三个方法。"""

    def __init__(self) -> None:
        self._subs: dict[type, list[Callable]] = {}

    def on(self, event_type: type, handler: Callable) -> Callable[[], None]:
        """订阅某类事件，返回退订函数（插件用来自动回收订阅）。"""
        self._subs.setdefault(event_type, []).append(handler)

        def unsubscribe() -> None:
            self.off(event_type, handler)

        return unsubscribe

    def off(self, event_type: type, handler: Callable) -> None:
        try:
            self._subs.get(event_type, []).remove(handler)
        except ValueError:
            pass

    def emit(self, event) -> None:
        """分发事件。遍历订阅者副本（防迭代中增删）；
        每个 handler 独立捕获异常——pyCraft 监听器里抛异常会炸掉网络线程直接断线，
        所以隔离异常不是可选项。"""
        for handler in list(self._subs.get(type(event), [])):
            try:
                handler(event)
            except Exception:
                logger.error("事件处理函数出错", exc_info=True)


# ---------------------------------------------------------------------------
# 事件定义（dataclass 实例，禁止用类属性当状态）
# ---------------------------------------------------------------------------

@dataclass
class ChatMessage:
    """一条聊天消息。发言人信息直接取自协议包字段。

    - sender / sender_uuid：玩家发言（PlayerChatPacket / 旧版 ChatMessagePacket）必有；
      系统消息（SystemChatPacket / ProfilelessChatPacket）协议上没有发言人字段，恒为 None。
    - text：component_text 解包后的发言内容，不含名字前缀。
    """
    text: str
    sender: str | None = None
    sender_uuid: UUID | None = None
    source: str = "system"  # legacy / player / system / profileless


@dataclass
class JoinedGame:
    """进入游戏世界（登录/配置阶段完成）。"""
    entity_id: int = 0
    world_name: str | None = None
    dimension: int | None = None
    game_mode: int | None = None
    world_names: list[str] = field(default_factory=list)


@dataclass
class WorldChanged:
    """重生或切换维度。"""
    world_name: str | None = None
    dimension: int | None = None
    game_mode: int | None = None


@dataclass
class PositionUpdated:
    """服务器校正/强制传送本玩家位置与视角。"""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0
    pitch: float = 0.0


@dataclass
class HealthUpdated:
    """生命值与饥饿值更新。"""
    health: float | None = None
    food: int | None = None
    saturation: float | None = None


@dataclass
class Kicked:
    """被服务器断开连接。"""
    reason: str = ""
    raw_json: str = ""


@dataclass
class Death:
    """机器人阵亡。

    现代协议（1.17+）没有专门的"自己死亡"包，检测依据是 UpdateHealthPacket
    的 health ≤ 0；bridge 做边沿检测（死亡期间重复的血量包不会重复触发），
    每次死亡只发一次。死亡后可用 bot.respawn() 重生。
    """
