"""
包→事件桥：全项目唯一与 pyCraft 包类型耦合的地方。

声明式映射表 _PACKET_EVENT_MAP：想处理新包，加一行映射即可；
个别特殊需求也可以在插件里直接用 connection.listener(...)（逃生舱口）。

另外，每个包到达都会刷新 PacketBridge.last_packet_at（含不产生事件的
KeepAlivePacket），这是 bot 判断"连接是活着还是已成僵尸"的唯一依据。

聊天发言人提取策略（从包字段提取，不做字符串正则）：
- PlayerChatPacket(1.19.1+)：sender_uuid + sender_name(759) / network_name(760+，765+ 为 NBT)；
  内容取 plain_message(761+) / signed_content(759) / unsigned_content(全部)。
- SystemChatPacket：协议上没有发言人字段，sender 恒为 None；
  ProfilelessChatPacket（伪装聊天）自带 name 字段，从其中提取发言人。
- ChatMessagePacket(<1.19)：json_data 的 "with" 数组按结构取 [发言人, 内容]。

映射表的值可以是单个事件工厂，也可以是工厂元组（同一包派生多个事件，
如 UpdateHealthPacket → HealthUpdated + Death）；有状态的检测器写成类，
attach() 时自动实例化（每个桥一份状态）。
"""

import json
import time

from minecraft.networking.connection import Connection
from minecraft.networking.packets import clientbound

from src.core.events import (
    ChatMessage,
    Death,
    EventBus,
    HealthUpdated,
    JoinedGame,
    Kicked,
    PositionUpdated,
    WorldChanged,
)

play = clientbound.play


def component_text(value) -> str:
    """从聊天组件提取纯文本。组件可能是：
    JSON 字符串（765 之前）、NBT 标签（765+，pynbt 对象）、或已是纯文本。"""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return value  # 已是纯文本
    if hasattr(value, "get"):  # dict 或 pynbt TAG_Compound
        text = value.get("text", "")
        if hasattr(text, "value"):  # 解包 pynbt 原始标签
            text = text.value
        text = str(text)
        extra = value.get("extra")
        if extra:
            text += "".join(component_text(item) for item in extra)
        return text
    if hasattr(value, "value"):  # 原始 pynbt 标签，如 TAG_String
        return str(value.value)
    return str(value)


def _first_attr(packet, names, default=None):
    """按顺序取包身上第一个存在的字段。"""
    for name in names:
        value = getattr(packet, name, None)
        if value is not None:
            return value
    return default


# ---------------------------------------------------------------------------
# 事件工厂：包 → 事件（返回 None 表示忽略该包）
# ---------------------------------------------------------------------------


def _make_player_chat(packet) -> ChatMessage:
    """PlayerChatPacket（1.19.1+）：玩家发言，自带发言人字段。"""
    raw_name = _first_attr(packet, ("sender_name", "network_name"))
    sender = component_text(raw_name) if raw_name is not None else None
    text = component_text(
        _first_attr(packet, ("plain_message", "signed_content", "unsigned_content"), "")
    )
    return ChatMessage(
        text=text,
        sender=sender,
        sender_uuid=getattr(packet, "sender_uuid", None),
        source="player",
    )


def _make_system_chat(packet) -> ChatMessage:
    """SystemChatPacket（1.19+）：系统提示，协议上无发言人。"""
    return ChatMessage(text=component_text(packet.content), source="system")


def _make_profileless_chat(packet) -> ChatMessage:
    """ProfilelessChatPacket（1.19.3+，现名 DisguisedChatPacket 伪装聊天）：
    发言人是协议自带的 name 字段（765+ 为 NBT 组件），不能丢弃。"""
    raw_name = getattr(packet, "name", None)
    sender = component_text(raw_name) if raw_name is not None else None
    return ChatMessage(
        text=component_text(packet.message),
        sender=sender,
        source="profileless",
    )


def _make_legacy_chat(packet) -> ChatMessage:
    """ChatMessagePacket（<1.19）：从 json_data 的 with 数组按结构提取。"""
    try:
        data = json.loads(packet.json_data)
    except (ValueError, TypeError):
        return ChatMessage(text=component_text(packet.json_data), source="legacy")
    parts = data.get("with") if hasattr(data, "get") else None
    if isinstance(parts, list) and len(parts) >= 2:
        return ChatMessage(
            text=component_text(parts[1]),
            sender=component_text(parts[0]),
            source="legacy",
        )
    return ChatMessage(text=component_text(data), source="legacy")


def _make_joined_game(packet) -> JoinedGame:
    """JoinGamePacket。dimension/world_name 走 AbstractDimensionPacket 的
    版本无关属性（766+ 藏在 world_state 里），不直接摸 world_state。"""
    game_mode = getattr(packet, "game_mode", None)
    world_state = getattr(packet, "world_state", None)
    if game_mode is None and world_state is not None:
        game_mode = getattr(world_state, "game_mode", None)
    return JoinedGame(
        entity_id=getattr(packet, "entity_id", 0),
        world_name=getattr(packet, "world_name", None),
        dimension=getattr(packet, "dimension", None),
        game_mode=game_mode,
        world_names=list(getattr(packet, "world_names", None) or []),
    )


def _make_world_changed(packet) -> WorldChanged:
    """RespawnPacket：重生/切换维度都会触发。"""
    game_mode = getattr(packet, "game_mode", None)
    world_state = getattr(packet, "world_state", None)
    if game_mode is None and world_state is not None:
        game_mode = getattr(world_state, "game_mode", None)
    return WorldChanged(
        world_name=getattr(packet, "world_name", None),
        dimension=getattr(packet, "dimension", None),
        game_mode=game_mode,
    )


def _make_position_updated(packet) -> PositionUpdated:
    # 注意：不用 early=True 监听——TeleportConfirm 回复是 pyCraft 内置动作。
    return PositionUpdated(
        x=packet.x, y=packet.y, z=packet.z, yaw=packet.yaw, pitch=packet.pitch
    )


def _make_health_updated(packet) -> HealthUpdated:
    return HealthUpdated(
        health=packet.health, food=packet.food, saturation=packet.food_saturation
    )


class _DeathDetector:
    """阵亡边沿检测器：health 从 >0 变为 ≤0 的那一发包才产生 Death 事件，
    死亡期间后续的 0 血量包不会重复触发；重生（health 恢复 >0）后重新武装。"""

    def __init__(self) -> None:
        self.was_dead = False

    def __call__(self, packet) -> Death | None:
        health = getattr(packet, "health", None)
        dead = health is not None and health <= 0
        if dead and not self.was_dead:
            self.was_dead = True
            return Death()
        if not dead:
            self.was_dead = False
        return None


def _make_kicked(packet) -> Kicked:
    json_str = getattr(packet, "json_data", "")
    return Kicked(reason=component_text(json_str), raw_json=json_str)


def _make_keep_alive(packet) -> None:
    """KeepAlivePacket：服务器约每 15–20 秒发一次（pyCraft 会自动回包）。

    这里刻意不产生业务事件（返回 None），只为让"包到达时间戳"被
    PacketBridge 刷新——bot 的假死看门狗靠"最近一次收到任意包"判断连接
    是否还活着。FRP 隧道半开时该包停止到达，这是客户端唯一可观测的掉线信号。
    """
    return None


# 声明式映射表：包类型 → 事件工厂。加事件只改这一处。
_PACKET_EVENT_MAP = {
    play.JoinGamePacket: _make_joined_game,
    play.RespawnPacket: _make_world_changed,
    play.PlayerPositionAndLookPacket: _make_position_updated,
    play.UpdateHealthPacket: (_make_health_updated, _DeathDetector),
    play.DisconnectPacket: _make_kicked,
    # 心跳包不产生事件，只用来刷新存活时间戳（见 _make_keep_alive）。
    play.KeepAlivePacket: _make_keep_alive,
    play.ChatMessagePacket: _make_legacy_chat,
    play.PlayerChatPacket: _make_player_chat,
    play.SystemChatPacket: _make_system_chat,
    play.ProfilelessChatPacket: _make_profileless_chat,
}


class PacketBridge:
    """把映射表挂到 Connection 上：包到达 → 工厂翻译 → 总线分发。

    last_packet_at 记录最近一次收到任意已监听包的时刻（time.monotonic），
    由网络线程单写、其他线程只读（CPython 下 float 赋值原子），
    供 bot 的假死看门狗判断连接里是否还有数据流入。
    """

    def __init__(self, connection: Connection, bus: EventBus) -> None:
        self.connection = connection
        self.bus = bus
        #: 最近一次收到包的时刻（time.monotonic）；None = 还没收到过任何包
        self.last_packet_at: float | None = None

    def attach(self) -> None:
        """注册所有监听器。必须在 connect() 之前调用，否则漏收 JoinGame 等早期包。"""
        for packet_type, factories in _PACKET_EVENT_MAP.items():
            if not isinstance(factories, tuple):
                factories = (factories,)
            for factory in factories:
                # 有状态的检测器写成类，这里实例化，保证每个桥一份独立状态。
                self._register(
                    packet_type, factory() if isinstance(factory, type) else factory
                )

    def _register(self, packet_type, factory) -> None:
        @self.connection.listener(packet_type)
        def on_packet(packet):
            # 任何已监听包到达都刷新存活时间戳（含不产生事件的心跳包）。
            self.last_packet_at = time.monotonic()
            event = factory(packet)
            if event is not None:
                self.bus.emit(event)
