"""
Bot 门面：全项目的组装点与生命周期枢纽。

生命周期：create_connection(认证) → 挂桥/指令 → 插件 setup_all → connect
         → 主线程等待（Ctrl+C / request_stop）→ 主线程 stop（disconnect + 逆序注销插件）

铁律：
- 所有事件回调在 pyCraft 单一网络线程串行执行，回调内禁止阻塞；
- 只有主线程允许调 stop()（内含 disconnect）；回调里只允许 request_stop()；
- write_packet 在 connect() 之后才合法，所有发送方法都带 connected 检查。
"""
import signal
import threading
import traceback

from minecraft.networking.packets import serverbound

import config
from src.core.auth import create_connection
from src.core.bridge import PacketBridge
from src.core.commands import CommandRegistry
from src.core.events import EventBus, Kicked
from src.core.plugin import PluginManager
from src.core.state import BotState


class Bot:
    """组装认证、事件总线、状态、指令系统与插件管理器，并对外暴露发送 API。"""

    def __init__(self) -> None:
        self.events = EventBus()
        self.state = BotState()
        # 认证可能阻塞（首次运行的设备码授权流程），此时还没有任何 socket。
        self.connection = create_connection()
        self.state.self_name = self.connection.username

        # 包监听器必须早于 connect() 挂上，否则漏收 JoinGame 等早期包。
        PacketBridge(self.connection, self.events).attach()

        # 命令注册
        self.commands = CommandRegistry(self)
        self.commands.start()
        # 被踢（DisconnectPacket）时 pyCraft 走正常断开流程、不抛异常，
        # handle_exception 不会被触发，必须自行监听 Kicked 收尾。
        self.events.on(Kicked, self._on_kicked)

        self.plugins = PluginManager(self)
        self._stop_event = threading.Event()
        # 网络线程崩溃兜底（服务器崩/被踢/漏网异常）：打印并走正常退出流程。
        self.connection.handle_exception = self._on_network_error

    # --- 生命周期 ---

    def run(self) -> None:
        """启动机器人：插件就绪 → 连接 → 主线程阻塞等待停止信号。"""
        self._register_signal_handlers()
        self.plugins.setup_all()
        try:
            self.connection.connect()
        except Exception:
            print("[bot] 连接失败:")
            traceback.print_exc()
            return
        self.state.connected = True
        print("[bot] 已连接，按 Ctrl+C 退出")
        try:
            while not self._stop_event.wait(0.5):
                pass
        except KeyboardInterrupt:
            print()
        finally:
            self.stop()

    def stop(self) -> None:
        """只在主线程调用：断开连接并逆序注销全部插件。"""
        self._stop_event.set()
        if self.state.connected:
            self.state.connected = False
            try:
                self.connection.disconnect()
            except Exception:
                print("[bot] 断开连接时出错:")
                traceback.print_exc()
        self.commands.stop()
        self.plugins.teardown_all()
        print("[bot] 已退出")

    def request_stop(self) -> None:
        """回调/插件内唯一合法的停止方式：只置停止标志，主线程自然收尾。"""
        self._stop_event.set()

    def _register_signal_handlers(self) -> None:
        """把外部终止信号接入 request_stop：SIGTERM（kill / docker stop）
        与 SIGBREAK（Windows 关控制台 / Ctrl+Break）也会走 stop() 的完整收尾
        （disconnect + 插件 teardown），而不是被系统直接杀掉、跳过一切清理。
        Ctrl+C（SIGINT）保持默认 KeyboardInterrupt 路径不变。
        signal.signal 只能在主线程注册，run() 恰在主线程执行。"""
        def _handler(signum, _frame) -> None:
            print(f"[bot] 收到信号 {signum}，准备退出")
            self.request_stop()

        for name in ("SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue  # 当前平台没有该信号（如 Linux 无 SIGBREAK）
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                print(f"[bot] 注册 {name} 失败，该信号将走系统默认行为")

    def _on_network_error(self, exc, exc_info) -> None:
        print("[bot] 网络线程异常:")
        print(exc)
        # traceback.print_exception(type(exc), exc, exc_info)
        self.state.connected = False
        self.request_stop()

    def _on_kicked(self, event: Kicked) -> None:
        """网络线程回调：被服务器踢出。断开由 pyCraft 完成，这里只负责收尾，
        让主线程 stop() 完成指令退订与插件线程回收。"""
        self.state.connected = False
        self.request_stop()

    # --- 发送 API（connect 之前一律返回 False，防止 write_packet 崩溃） ---

    def chat(self, text: str) -> bool:
        """发送聊天或命令。协议上限 256 字符，超长自动截断。"""
        if text.startswith('/'):
            return self.send_server_command(text)
        if not self.state.connected:
            return False
        packet = serverbound.play.ChatPacket()
        packet.message = text[:256]
        self.connection.write_packet(packet)
        return True

    def send_server_command(self, cmd: str) -> bool:
        """发送服务器命令（自动去掉前导 '/'）。协议 ≥759 用 ChatCommandPacket，
        更早版本只能以普通聊天发送 "/cmd" 字符串。"""
        cmd = cmd.lstrip("/")
        if not cmd or not self.state.connected:
            return False
        if self.connection.context.protocol_later_eq(759):
            packet = serverbound.play.ChatCommandPacket()
            packet.command = cmd
        else:
            packet = serverbound.play.ChatPacket()
            packet.message = "/" + cmd
        self.connection.write_packet(packet)
        return True

    def respawn(self) -> bool:
        """死亡后请求重生。"""
        if not self.state.connected:
            return False
        packet = serverbound.play.ClientStatusPacket()
        packet.action_id = serverbound.play.ClientStatusPacket.RESPAWN
        self.connection.write_packet(packet)
        return True
