"""资源包观测层：服务器下发的资源包写进日志，应答交给 pyCraft 内置处理。

背景（2026-09 实测于某真实服务器）：
服务器在 configuration 阶段下发资源包后，必须收到客户端应答，否则永远不发
FinishConfiguration，连接就永久停在 configuration 阶段——客户端表现为"正版认证成功、
LoginSuccess 也收到了，但迟迟收不到 JoinGame"，直到登录超时。

pyCraft 0.7.4 起已内置该能力（数据包定义 + reactor 默认应答 +
Connection.handle_resource_pack 钩子），因此本模块只剩"观测"这一件事：

- 挂监听器记录服务器下发/撤销的资源包，运维在 logs/bot.txt 里能看到现场；
- 应答完全交给上游 reactor 的默认策略（ACCEPTED → DOWNLOADED → SUCCESSFULLY_LOADED，
  不下载内容）。刻意**不设置** Connection.handle_resource_pack，以免把上游的默认策略
  复制一份到项目里、日后与上游行为漂移；
- 不 patch pyCraft 的任何内部结构。

版本要求：pycraft-minecraft >= 0.7.4，低于该版本**直接抛错终止启动**。
旧库缺少资源包数据包定义，连上去只会卡在 configuration 直到登录超时（现象与"服务器
无响应"完全一样，极难诊断），启动即失败比静默卡死好得多。

需要自定义策略（拒绝、真下载、只记日志不回应等）时不必改这里：给
`Connection(..., handle_resource_pack=...)` 传回调即可，契约是
`fn(packet) -> iterable[Result | int] | None`（None 表示完全不回应）。
"""
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version

from minecraft.networking.connection import Connection
from minecraft.networking.packets.clientbound import configuration as clientbound_configuration

from src.core.logger import get_logger

logger = get_logger(__name__)

#: 本模块要求的最低 pyCraft 版本：0.7.4 起才内置资源包支持
REQUIRED_PYCRAFT_VERSION = "0.7.4"
#: 分发包名（import 名是 minecraft）
_PYCRAFT_DISTRIBUTION = "pycraft-minecraft"


def _installed_pycraft_version() -> str:
    """当前安装的 pyCraft 版本；拿不到时返回占位说明（不影响判定）。"""
    try:
        return package_version(_PYCRAFT_DISTRIBUTION)
    except PackageNotFoundError:
        return "未知（非 pip 安装）"


def _require_resource_pack_support() -> None:
    """缺少资源包支持就立刻终止启动，并给出可直接执行的修复指引。"""
    if hasattr(clientbound_configuration, "AddResourcePackPacket"):
        return
    current = _installed_pycraft_version()
    logger.error(
        "pyCraft 版本过低（当前 %s）：缺少资源包数据包定义，连接会卡在 configuration "
        "阶段直到登录超时，因此终止启动",
        current,
    )
    logger.error(
        '请执行：pip install -U "%s>=%s"', _PYCRAFT_DISTRIBUTION, REQUIRED_PYCRAFT_VERSION
    )
    raise RuntimeError(
        "%s >= %s is required for resource pack support (installed: %s)"
        % (_PYCRAFT_DISTRIBUTION, REQUIRED_PYCRAFT_VERSION, current)
    )


def install(connection: Connection) -> None:
    """挂上资源包观测层。必须在 connect() 之前调用。

    版本不足时抛 RuntimeError，由 main() 的顶层兜底记录并退出（不启动服务）。
    """
    _require_resource_pack_support()
    _install_observers(connection)
    logger.info(
        "资源包应答由 pyCraft %s 内置能力处理（回报加载完成，不下载内容）",
        _installed_pycraft_version(),
    )


def _install_observers(connection: Connection) -> None:
    """只做记录：应答由 pyCraft reactor 的默认策略完成，这里不干预。"""
    from minecraft.networking.packets.clientbound import play as clientbound_play

    def on_resource_pack(packet):
        url = getattr(packet, "url", None)
        if url:
            logger.info(
                "服务器下发资源包：%s（forced=%s，hash=%s）",
                url,
                getattr(packet, "forced", None),
                (getattr(packet, "hash", None) or "")[:12],
            )
        else:
            logger.info(
                "服务器撤销资源包：uuid=%s",
                getattr(packet, "uuid", None) or "（全部）",
            )

    for module in (clientbound_configuration, clientbound_play):
        for name in (
            "AddResourcePackPacket",       # 765+：configuration 与 play
            "ResourcePackSendPacket",      # 764：旧式资源包包
            "RemoveResourcePackPacket",    # 撤销资源包
        ):
            packet_type = getattr(module, name, None)
            if packet_type is not None:
                connection.register_packet_listener(on_resource_pack, packet_type)
