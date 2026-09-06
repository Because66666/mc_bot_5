from src.core.events import Death
from src.core.plugin import Plugin


class AutoRespawnPlugin(Plugin):
    name = "auto_respawn"

    def setup(self) -> None:
        "死亡后选择自动复活"
        self.on(Death, self.respawn_func)

    def respawn_func(self, event: Death):
        try:
            self.bot.respawn()
            # 死亡后复活，传送由另外一个时间表插件实现。
        except Exception as e:
            print(f"[error] 自动复活失败：{e}")
