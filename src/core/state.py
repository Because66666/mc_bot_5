"""
机器人状态数据类。

约束：
- 唯一写者是 state_tracker 插件（在网络线程执行）；主线程仅在 stop 之后读取，无需加锁。
- 必须创建实例使用（BotState()），禁止把字段写在类属性上共享。
"""
from dataclasses import dataclass, field


@dataclass
class WorldInfo:
    """当前所在世界的信息。"""
    world_name: str | None = None       # 如 "minecraft:overworld"
    dimension: int | None = None        # 0 = 主世界
    game_mode: int | None = None        # 0=生存 1=创造 2=冒险 3=旁观
    world_names: list[str] = field(default_factory=list)


@dataclass
class BotState:
    """机器人自身状态快照。"""
    self_name: str | None = None        # 自己的玩家名（来自认证结果）
    connected: bool = False
    entity_id: int | None = None
    position: tuple[float, float, float] | None = None
    look: tuple[float, float] | None = None     # (yaw, pitch)
    health: float | None = None
    food: int | None = None
    dead: bool = False        # 是否处于死亡/重生界面状态
    world: WorldInfo = field(default_factory=WorldInfo)
