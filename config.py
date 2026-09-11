"""
静态配置常量——改参数只动这里。
"""
import os
from dotenv import load_dotenv
import socket

load_dotenv()
#: Microsoft 账号邮箱，仅用于令牌缓存命名与登录打印，可留空。
USERNAME = os.getenv('PLAYERNAME','')
#: 服务器地址与端口。
DOMAIN = os.getenv('DOMAIN','')
if DOMAIN:
    ADDRESS = socket.gethostbyname(DOMAIN)
PORT = 25565
#: Microsoft 令牌缓存目录；None 表示默认位置（~/.minecraft/nmp-cache）。
CACHE_DIR = None
#: 触发机器人指令的聊天前缀。
COMMAND_PREFIX = "!"
