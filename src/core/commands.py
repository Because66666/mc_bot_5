"""
聊天指令系统：监听 ChatMessage 事件，按前缀解析并分发给注册的 handler。

解析流程（全程同步、微秒级，跑在网络线程）：
    ChatMessage → text 以 prefix 开头？→ split 出指令名与参数
    → 查注册表 → handler(CommandContext)（整体 try/except，出错回复提示）

sender 来自包字段：玩家发言必有，系统消息为 None（协议无此字段），
handler 自行决定如何使用。自己发言的回显按 sender 名字过滤，防止自触发循环。
"""
from dataclasses import dataclass, field
from typing import Callable

import config
from src.core.events import ChatMessage
from src.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CommandContext:
    """传给指令 handler 的上下文。"""
    bot: object                 # Bot 门面：发聊天、读状态、调其他能力
    sender: str | None          # 发言人玩家名；系统消息为 None
    args: list[str] = field(default_factory=list)   # "!tpa Steve" → ["Steve"]


class CommandRegistry:
    """指令注册表。内部就是 dict，够用；不做参数类型解析（需要时再加）。"""

    def __init__(self, bot, prefix: str = config.COMMAND_PREFIX) -> None:
        self.bot = bot
        self.prefix = prefix
        self._commands: dict[str, tuple[Callable, str]] = {}
        self._unsubscribe: Callable[[], None] | None = None
        self.register("help", self._help_cmd, "列出可用指令")

    # --- 注册 API ---

    def register(self, name: str, handler: Callable, help_text: str = "") -> None:
        """函数式注册：register("hello", fn, "打招呼")。"""
        self._commands[name.lower()] = (handler, help_text)

    def command(self, name: str, help_text: str = "") -> Callable:
        """装饰器注册：@bot.commands.command("hello", "打招呼")。"""
        def decorator(handler: Callable) -> Callable:
            self.register(name, handler, help_text)
            return handler
        return decorator

    # --- 生命周期 ---

    def start(self) -> None:
        """订阅聊天事件。必须在 connect() 之前调用，否则漏早期消息。"""
        self._unsubscribe = self.bot.events.on(ChatMessage, self._on_chat)

    def stop(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    # --- 解析与分发 ---

    def _on_chat(self, event: ChatMessage) -> None:
        # 自己发言的回显不处理，否则形如 "!help xxx" 的回复会触发自身循环。
        if event.sender is not None and event.sender == self.bot.state.self_name:
            return
        text = event.text.strip()
        if not text.startswith(self.prefix):
            return
        body = text[len(self.prefix):].strip()
        if not body:
            return
        parts = body.split()
        name, args = parts[0].lower(), parts[1:]
        entry = self._commands.get(name)
        if entry is None:
            self.bot.chat(f"未知指令 {self.prefix}{name}，试试 {self.prefix}help")
            return
        handler, _help = entry
        try:
            handler(CommandContext(bot=self.bot, sender=event.sender, args=args))
        except Exception:
            logger.error("指令 %s%s 执行出错", self.prefix, name, exc_info=True)
            self.bot.chat(f"指令 {self.prefix}{name} 执行出错")

    def _help_cmd(self, ctx: CommandContext) -> None:
        lines = [f"{self.prefix}{name} {help_text}".strip()
                 for name, (_handler, help_text) in sorted(self._commands.items())]
        self.bot.chat(" | ".join(lines))
