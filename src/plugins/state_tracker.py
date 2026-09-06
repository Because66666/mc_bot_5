"""
内置插件：把事件回填到 bot.state。

state 的唯一写者（在网络线程执行）；其他插件只读 bot.state 即可获得
位置、血量、世界等实时快照，不必各自监听包。
"""
from src.core.events import (
    Death,
    HealthUpdated,
    JoinedGame,
    Kicked,
    PositionUpdated,
    WorldChanged,
)
from src.core.plugin import Plugin


class StateTracker(Plugin):
    name = "state_tracker"

    def setup(self) -> None:
        self.on(JoinedGame, self._on_joined)
        self.on(WorldChanged, self._on_world_changed)
        self.on(PositionUpdated, self._on_position)
        self.on(HealthUpdated, self._on_health)
        self.on(Death, self._on_death)
        self.on(Kicked, self._on_kicked)

    def _on_joined(self, event: JoinedGame) -> None:
        state = self.bot.state
        state.entity_id = event.entity_id
        world = state.world
        world.world_name = event.world_name
        world.dimension = event.dimension
        world.game_mode = event.game_mode
        world.world_names = list(event.world_names)

    def _on_world_changed(self, event: WorldChanged) -> None:
        world = self.bot.state.world
        world.world_name = event.world_name
        world.dimension = event.dimension
        world.game_mode = event.game_mode

    def _on_position(self, event: PositionUpdated) -> None:
        self.bot.state.position = (event.x, event.y, event.z)
        self.bot.state.look = (event.yaw, event.pitch)

    def _on_health(self, event: HealthUpdated) -> None:
        state = self.bot.state
        state.health = event.health
        state.food = event.food
        if event.health is not None:
            state.dead = event.health <= 0

    def _on_death(self, event: Death) -> None:
        self.bot.state.dead = True

    def _on_kicked(self, event: Kicked) -> None:
        # print(f"[state] 被服务器断开: {event.reason}")
        pass
