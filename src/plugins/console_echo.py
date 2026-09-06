"""
内置插件：把关键事件回显到控制台（原 listener.py 的打印逻辑插件化）。

只做展示、不含逻辑；在 main.py 注释掉注册即可整体关闭。
"""
from src.core.events import (
    ChatMessage,
    Death,
    HealthUpdated,
    JoinedGame,
    Kicked,
    PositionUpdated,
    WorldChanged,
)
from src.core.plugin import Plugin


class ConsoleEcho(Plugin):
    name = "console_echo"

    def setup(self) -> None:
        self.on(ChatMessage, self._on_chat)
        self.on(JoinedGame, self._on_joined)
        self.on(WorldChanged, self._on_world_changed)
        self.on(PositionUpdated, self._on_position)
        self.on(HealthUpdated, self._on_health)
        self.on(Death, self._on_death)
        self.on(Kicked, self._on_kicked)

    def _on_chat(self, event: ChatMessage) -> None:
        if event.sender:
            print(f"[chat] <{event.sender}> {event.text}")
        else:
            print(f"[chat] {event.text}")

    def _on_joined(self, event: JoinedGame) -> None:
        print(f"[event] 加入游戏 (entity_id={event.entity_id}, world={event.world_name})")

    def _on_world_changed(self, event: WorldChanged) -> None:
        print(f"[event] 切换世界: {event.world_name} (dimension={event.dimension})")

    def _on_position(self, event: PositionUpdated) -> None:
        print(f"[teleport] x={event.x:.2f} y={event.y:.2f} z={event.z:.2f} "
              f"yaw={event.yaw:.1f} pitch={event.pitch:.1f}")

    def _on_health(self, event: HealthUpdated) -> None:
        print(f"[health] 生命={event.health} 饱腹={event.food}")

    def _on_death(self, event: Death) -> None:
        print("[event] 机器人阵亡（可调用 bot.respawn() 重生）")

    def _on_kicked(self, event: Kicked) -> None:
        print(f"[event] 被服务器断开: {event.reason}")
