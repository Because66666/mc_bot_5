"""
Microsoft 设备码流程认证，产出一个尚未 connect() 的 Connection。

首次运行会阻塞等待浏览器授权，属预期行为；之后复用缓存令牌。
"""
import socket
import sys

from minecraft import authentication
from minecraft.exceptions import YggdrasilError
from minecraft.networking.connection import Connection
import config

from src.core.logger import get_logger

logger = get_logger(__name__)


def on_device_code(data: dict) -> None:
    # 需要用户去浏览器完成授权，默认等级（WARNING）下也必须可见
    logger.warning("访问 %s?otc=%s 以授权。", data["verification_uri"], data["user_code"])


def resolve_address(domain: str) -> str:
    """把 .env 里的域名解析成 IPv4 字面量。

    解析放在这里而不是 config.py 的 import 期：import 期失败只会打到 stderr 的
    裸 traceback，日志文件里一片空白；这里失败会先落一条 ERROR 再向上抛。
    """
    if not domain:
        raise RuntimeError("未配置 DOMAIN（.env），无法确定服务器地址")
    try:
        address = socket.gethostbyname(domain)
    except OSError as error:  # gaierror 是 OSError 的子类
        logger.error("域名 %s 解析失败: %s", domain, error)
        raise
    logger.info("目标服务器 %s → %s:%s", domain, address, config.PORT)
    return address


def create_connection() -> Connection:
    """完成认证并创建连接对象。不负责 connect()，那是 Bot.run 的职责。"""
    address = resolve_address(config.DOMAIN)
    # 如果不是邮箱，则使用离线登录
    username = config.USERNAME
    if "@" not in username:
        logger.info("以 %s 身份离线登录", username)
        return Connection(address=address, port=config.PORT, username=username)
    auth_token = authentication.MicrosoftAuthenticationToken()
    try:
        auth_token.authenticate(
            username, cache_dir=config.CACHE_DIR, on_device_code=on_device_code
        )
    except YggdrasilError as error:
        logger.error("正版登录失败: %s", error)
        sys.exit(1)
    logger.info("以 %s 身份正版登录", auth_token.username)

    connection = Connection(address, config.PORT, auth_token=auth_token)
    # 使用 auth_token 时 Connection.username 保持 None，这里统一回填真实玩家名，
    # 供 state.self_name / 回声过滤使用。
    connection.username = auth_token.username
    return connection
