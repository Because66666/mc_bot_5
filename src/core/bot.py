"""
Bot 门面：全项目的组装点与生命周期枢纽。

生命周期：create_connection(认证) → 挂桥/指令 → 插件 setup_all → connect
         → 等 JoinGame（登录超时看门狗）→ 主线程等待（Ctrl+C / request_stop）
         → 主线程 stop（disconnect + 逆序注销插件）

存活判定（本层不做重连：发现异常就退出进程，由 supervisor 重拉）：
- connect() 返回只代表 TCP 连上，不代表登录成功：等不到 JoinGame 就退出；
- 进入游戏后看门狗线程盯着 bridge.last_packet_at，超过 IDLE_TIMEOUT 秒没有
  任何入站包即判定连接假死。FRP 隧道半开时 socket 既收不到 FIN 也没有 RST、
  写操作还会"成功"，pyCraft 不抛任何异常，"入站包停了"是唯一可观测的信号；
- 判定异常后若收尾卡住，FORCE_EXIT_DELAY 秒后强制结束进程（进程不退，
  supervisor 就永远不会重拉）。

铁律：
- 所有事件回调在 pyCraft 单一网络线程串行执行，回调内禁止阻塞；
- 只有主线程允许调 stop()（内含 disconnect）；回调里只允许 request_stop()；
- write_packet 在 connect() 之后才合法，所有发送方法都带 connected 检查。
"""
import logging
import os
import signal
import threading
import time

from minecraft.exceptions import LoginDisconnect
from minecraft.networking.packets import serverbound

import config
from src.core import compat
from src.core.auth import create_connection
from src.core.bridge import PacketBridge
from src.core.commands import CommandRegistry
from src.core.events import EventBus, JoinedGame, Kicked
from src.core.logger import get_logger
from src.core.plugin import PluginManager
from src.core.state import BotState

logger = get_logger(__name__)


class Bot:
    """组装认证、事件总线、状态、指令系统与插件管理器，并对外暴露发送 API。"""

    #: 进入游戏后允许的最长"无任何入站包"时间（秒）：服务器约每 15–20 秒发一次
    #: KeepAlive，取 4 倍余量。服务端自定义了更长的 keepalive 间隔时需调大。
    IDLE_TIMEOUT = 60.0
    #: 看门狗线程的检查间隔（秒）。
    WATCHDOG_INTERVAL = 5.0
    #: 登录超时（秒）：connect() 之后多久没收到 JoinGame 就判定连接异常。
    #: 要给状态查询 + 二次连接 + 配置阶段（1.20.2+）留足时间。
    LOGIN_TIMEOUT = 90.0
    #: 收尾兜底（秒）：判定异常后主线程若仍未退出，强制结束进程。
    FORCE_EXIT_DELAY = 10.0

    def __init__(self) -> None:
        self.events = EventBus()
        self.state = BotState()
        # 认证可能阻塞（首次运行的设备码授权流程），此时还没有任何 socket。
        self.connection = create_connection()
        self.state.self_name = self.connection.username

        # 包监听器必须早于 connect() 挂上，否则漏收 JoinGame 等早期包。
        # bridge 同时维护"最近一次收到包"的时间戳，供下面的看门狗使用。
        self.bridge = PacketBridge(self.connection, self.events)
        self.bridge.attach()
        # 资源包观测层：应答由 pyCraft 内置 reactor 完成，本模块只记录日志。
        # 服务器在 configuration 阶段下发资源包后必须收到应答，否则永远收不到
        # FinishConfiguration（表现为"登录成功却收不到 JoinGame"）。pyCraft 低于
        # 0.7.4 没有这个能力，install() 会直接抛错终止启动。详见 compat 模块注释。
        compat.install(self.connection)

        # 命令注册
        self.commands = CommandRegistry(self)
        self.commands.start()
        # 被踢（DisconnectPacket）时 pyCraft 走正常断开流程、不抛异常，
        # handle_exception 不会被触发，必须自行监听 Kicked 收尾。
        self.events.on(Kicked, self._on_kicked)
        # 登录完成的唯一判据：收到 JoinGame 才算真正进入游戏世界。
        self.events.on(JoinedGame, self._on_joined_game)
        self._joined = threading.Event()

        self.plugins = PluginManager(self)
        self._stop_event = threading.Event()
        # 是否正在主动关闭连接：主动关闭会让读 socket 的网络线程抛异常，
        # 那种异常是正常噪音，不能记成 ERROR（否则真故障会被噪音淹没）。
        self._closing = False
        # 网络线程崩溃兜底（服务器崩/被踢/漏网异常）：打印并走正常退出流程。
        self.connection.handle_exception = self._on_network_error
        # 网络线程"无异常地"结束（连接被对端关闭、socket 静默失效）时也必须唤醒
        # 主线程：不注册这个钩子的话这种结束是完全静默的，主线程会一直等下去。
        self.connection.handle_exit = self._on_network_exit

    # --- 生命周期 ---

    def run(self) -> None:
        """启动机器人：插件就绪 → 连接 → 等登录完成 → 主线程阻塞等待停止信号。

        connect() 返回只代表 TCP 连上并发出握手，登录还在网络线程里进行；
        因此必须等 _joined（JoinGame），超时即判定连接异常并退出进程。
        """
        self._register_signal_handlers()
        self.plugins.setup_all()
        try:
            self.connection.connect()
        except ConnectionRefusedError:
            logger.warning("服务器暂未开启，程序退出。")
            return
        except Exception:
            logger.error("连接失败", exc_info=True)
            return

        self._start_watchdog()
        try:
            if not self._wait_for_login():
                return
            logger.info("已进入游戏，按 Ctrl+C 退出")
            while not self._stop_event.wait(0.5):
                pass
        except KeyboardInterrupt:
            logger.info("收到 Ctrl+C，准备退出")
        finally:
            self.stop()

    def _wait_for_login(self) -> bool:
        """等登录完成；网络线程先失败/被踢时立刻返回 False。

        不能只写 _joined.wait(LOGIN_TIMEOUT)：网络线程可能 1 秒内就失败了
        （登录被服务器拒绝、连接被对端关闭），而主线程若只等 _joined，就要
        空等满 LOGIN_TIMEOUT，还会把已经记录下来的真实原因盖在"登录超时"后面。
        """
        deadline = time.monotonic() + self.LOGIN_TIMEOUT
        while not self._joined.is_set():
            if self._stop_event.wait(0.5):
                logger.error("连接在登录完成前终止，退出进程（真实原因见上一条日志）")
                return False
            if time.monotonic() >= deadline:
                logger.error(
                    "登录超时：%.0f 秒内没收到 JoinGame（连接半开或服务器无响应），"
                    "退出进程等待 supervisor 重连",
                    self.LOGIN_TIMEOUT,
                )
                self._force_exit_later()
                return False
        return True

    def stop(self) -> None:
        """只在主线程调用：断开连接并逆序注销全部插件（可重复调用）。"""
        self._stop_event.set()
        self._close_connection()
        self.commands.stop()
        self.plugins.teardown_all()
        logger.info("已退出")

    def _close_connection(self) -> None:
        """关闭底层 socket：无论登录是否完成都要关，避免残留半开连接。

        immediate=True 不再 flush 待发队列——连接已经判定异常时往里写包没有意义。
        """
        self._closing = True  # 让 _on_network_error 区分"主动关闭"与真故障
        self.state.connected = False
        try:
            self.connection.disconnect(immediate=True)
        except Exception:
            logger.error("断开连接时出错", exc_info=True)

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
            logger.info("收到信号 %s，准备退出", signum)
            self.request_stop()

        for name in ("SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue  # 当前平台没有该信号（如 Linux 无 SIGBREAK）
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                logger.warning("注册信号 %s 失败，该信号将走系统默认行为", name)

    def _on_network_error(self, exc, exc_info) -> None:
        if self._closing or self._stop_event.is_set():
            # 主动收尾时网络线程正在读 socket，会抛 "I/O operation on closed file"。
            # 这是正常噪音：降到 INFO，别把它记成故障（真故障才用 ERROR + 调用栈）。
            logger.info("连接关闭过程中网络线程退出：%s", exc)
            self.state.connected = False
            return
        if isinstance(exc, LoginDisconnect):
            # 服务器主动拒绝登录：属于业务结果而非程序缺陷，不打调用栈。
            logger.error(
                "服务器拒绝登录：%s。请检查：① 该服务器是否要求正版验证（本机当前"
                "认证方式见上面 auth 日志）；② 账号是否在白名单；③ 换一个入口 IP 重试"
                "（同一域名可能有多个 A 记录，其中某台可能不响应）",
                exc,
            )
        else:
            # exc_info 是 pyCraft 传入的 sys.exc_info() 三元组，直接交给 logging 打栈
            logger.error("网络线程异常: %s", exc, exc_info=exc_info)
        self.state.connected = False
        self.request_stop()

    def _on_kicked(self, event: Kicked) -> None:
        """网络线程回调：被服务器踢出。断开由 pyCraft 完成，这里只负责收尾，
        让主线程 stop() 完成指令退订与插件线程回收。"""
        logger.warning("被服务器断开：%s", event.reason or "未知原因")
        self.state.connected = False
        self.request_stop()

    def _on_network_exit(self) -> None:
        """网络线程结束（非异常、非本进程主动断开）时的回调。

        pyCraft 只在"连接关闭且不是异常导致"时调用它。不注册这个钩子的话，
        这种结束是完全静默的：主线程会一直等在 _stop_event 上，进程既不退出
        也不重连，外部看起来就是"机器人在线"却什么也不做。
        """
        if self._stop_event.is_set():
            return  # 本进程正在主动退出，无需重复处理
        logger.warning("网络线程已结束，连接不再可用，准备退出进程")
        self.state.connected = False
        self.request_stop()

    def _on_joined_game(self, event: JoinedGame) -> None:
        """网络线程回调：登录完成、真正进入游戏世界。

        connected 的唯一置位点——connect() 返回只代表 TCP 连上，在那之前
        chat()/send_server_command() 都会因为未连接而拒绝发包。
        """
        self.state.connected = True
        self._joined.set()
        logger.info("已进入游戏世界（world=%s）", event.world_name)

    # --- 假死看门狗（对付 FRP 半开这类"僵尸连接"） ---

    def _start_watchdog(self) -> None:
        """启动存活看门狗线程（daemon，随进程退出，无需回收）。"""
        threading.Thread(
            target=self._watchdog_loop, name="bot-watchdog", daemon=True
        ).start()

    def _watchdog_loop(self) -> None:
        """后台线程：进入游戏后长时间收不到任何包 → 判定连接假死 → 退出进程。

        判定依据只有 bridge.last_packet_at：TCP 层已经无信号可用（半开连接
        没有 FIN/RST，写操作还会静默成功），而服务器约每 15–20 秒一个 KeepAlive，
        所以"入站包断流"是唯一可靠的掉线证据。
        """
        while not self._stop_event.wait(self.WATCHDOG_INTERVAL):
            if not self.state.connected:
                continue  # 没登录成功 / 已断开：不判定
            last_packet_at = self.bridge.last_packet_at
            if last_packet_at is None:
                continue
            idle = time.monotonic() - last_packet_at
            if idle < self.IDLE_TIMEOUT:
                continue
            logger.error(
                "连接假死：%.0f 秒没有收到任何服务器数据包（阈值 %.0f 秒），"
                "退出进程等待 supervisor 重连",
                idle,
                self.IDLE_TIMEOUT,
            )
            self._force_exit_later()
            self.request_stop()
            return

    def _force_exit_later(self) -> None:
        """兜底：给主线程 FORCE_EXIT_DELAY 秒完成收尾，超时直接结束进程。

        僵尸连接上 close() 一般不会阻塞，但收尾若因任何原因卡住，进程不退，
        supervisor 就永远不会重拉——这条硬退路是"必须能自愈"的最后保障。
        """
        timer = threading.Timer(self.FORCE_EXIT_DELAY, self._force_exit)
        timer.daemon = True
        timer.start()

    @staticmethod
    def _force_exit() -> None:
        logger.error("收尾超时，强制退出进程")
        logging.shutdown()  # 先把日志 flush 落盘，再硬退出
        os._exit(1)

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
