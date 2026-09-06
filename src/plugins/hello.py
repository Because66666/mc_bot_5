"""
示例插件：!hello 指令 → bot 在聊天里回复。

这是"加一个功能"的标准模板：
1. 写一个插件文件，继承 Plugin；
2. 在 setup() 里用 self.bot.commands.command(...) 注册指令；
3. 在 main.py 里 bot.plugins.register(你的插件) 一行启用。
"""
from src.core.commands import CommandContext
from src.core.plugin import Plugin


class HelloPlugin(Plugin):
    name = "hello"

    def setup(self) -> None:
        self.bot.commands.command("hello", "向机器人打招呼")(self._hello)

    def _hello(self, ctx: CommandContext) -> None:
        # 系统消息转发时 sender 可能为 None，做好兜底。
        self.bot.chat(f"你好, {ctx.sender or '朋友'}!")
