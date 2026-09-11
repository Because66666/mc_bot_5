"""
Microsoft 设备码流程认证，产出一个尚未 connect() 的 Connection。

首次运行会阻塞等待浏览器授权，属预期行为；之后复用缓存令牌。
"""

import sys

from minecraft import authentication
from minecraft.exceptions import YggdrasilError
from minecraft.networking.connection import Connection

import config


def on_device_code(data: dict) -> None:
    print(f"访问 {data['verification_uri']}?otc={data['user_code']} 以授权。")


def create_connection() -> Connection:
    """完成认证并创建连接对象。不负责 connect()，那是 Bot.run 的职责。"""
    # 如果不是邮箱，则使用离线登录
    username = config.USERNAME
    if "@" not in username:
        return Connection(address=config.ADDRESS, port=config.PORT, username=username)
    auth_token = authentication.MicrosoftAuthenticationToken()
    try:
        auth_token.authenticate(
            username, cache_dir=config.CACHE_DIR, on_device_code=on_device_code
        )
    except YggdrasilError as error:
        print(error)
        sys.exit(1)
    print("Logged in as %s..." % auth_token.username)

    connection = Connection(config.ADDRESS, config.PORT, auth_token=auth_token)
    # 使用 auth_token 时 Connection.username 保持 None，这里统一回填真实玩家名，
    # 供 state.self_name / 回声过滤使用。
    connection.username = auth_token.username
    return connection
