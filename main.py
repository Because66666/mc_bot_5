#!/usr/bin/env python
"""
组装根：全项目唯一入口。

流程：创建 Bot（内含认证）→ 注册要启用的插件 → run。
加一个新功能 = 在 src/plugins/ 写一个插件文件，然后在这里加一行 register。
"""
import os
import sys

# 保证从任意工作目录启动时都能找到本项目模块。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.core.bot import Bot  # noqa: E402
from src.plugins.console_echo import ConsoleEcho  # noqa: E402
from src.plugins.hello import HelloPlugin  # noqa: E402
from src.plugins.auto_respawn import AutoRespawnPlugin # 自动复活插件
from src.plugins.state_tracker import StateTracker  # noqa: E402
from src.plugins.home_schedule import HomeSchedulePlugin  # noqa: E402
from src.plugins.handle_request import Handle_Request_Plugin


def main() -> None:
    bot = Bot()
    # --- 在这里决定启用哪些功能（enabled=False 或注释掉即关闭）---
    bot.plugins.register(StateTracker)   # 事件 → bot.state 状态回填
    bot.plugins.register(ConsoleEcho)    # 控制台回显
    bot.plugins.register(HelloPlugin,enabled=False)    # !hello 示例指令
    bot.plugins.register(AutoRespawnPlugin) # 自动复活
    bot.plugins.register(Handle_Request_Plugin) # 自动应答，包含tpa承接
    bot.plugins.register(HomeSchedulePlugin) # 家园时间表：按表自动 /home

    bot.run()


if __name__ == "__main__":
    main()
