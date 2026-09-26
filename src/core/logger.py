"""
统一日志入口：src 下所有模块共用，不再用 print。

规则：
- 控制台等级默认 INFO（可用环境变量 LOG_LEVEL 覆盖，如 LOG_LEVEL=WARNING 恢复安静）；
- INFO 及以上同时写入 logs/bot.txt，单文件上限 1MB，超出自动轮转
  （bot.txt → bot.txt.1 → bot.txt.2 → bot.txt.3）；
- 用法：模块顶部 logger = get_logger(__name__)，然后 logger.info/warning/error。

为什么文件里也要 INFO：机器人最常见的故障形态是"进程活着但连接成了僵尸"
（FRP 半开、被踢、登录超时），现场只有 INFO 级叙事能还原。文件只留 ERROR 时，
日志会长时间空白，反而把故障伪装成"一切正常"。
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

#: 项目根目录（src/core/logger.py 往上三级）
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_FILE = LOG_DIR / "bot.txt"

#: 单文件大小上限 1MB，最多保留 3 个轮转备份
MAX_BYTES = 1024 * 1024
BACKUP_COUNT = 3

#: 默认等级：控制台与文件都是 INFO 及以上
DEFAULT_LEVEL = "INFO"

_FORMAT = "[%(asctime)s][%(levelname)s][%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def _resolve_level() -> int:
    """LOG_LEVEL 环境变量 → 等级数值；无法识别时回落默认等级。"""
    name = os.getenv("LOG_LEVEL", DEFAULT_LEVEL).upper()
    level = logging.getLevelName(name)
    if isinstance(level, int):
        return level
    # 配置尚未完成，这条 warning 走 logging 的 lastResort 输出到 stderr
    logging.getLogger(__name__).warning(
        "无法识别的 LOG_LEVEL=%r，改用 %s", name, DEFAULT_LEVEL
    )
    return logging.getLevelName(DEFAULT_LEVEL)


def setup_logging() -> None:
    """给 root logger 挂上控制台与文件两个 handler；重复调用无副作用。

    挂在 root 上，第三方库（pyCraft 等）的 warning/error 也会一并落地。
    """
    global _configured
    if _configured:
        return
    _configured = True

    level = _resolve_level()
    formatter = logging.Formatter(_FORMAT, _DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(level)  # 与默认等级一致：控制台看得到的历史，文件里也查得到
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)



def get_logger(name: str) -> logging.Logger:
    """取一个模块级 logger；首次调用顺带完成全局配置。"""
    setup_logging()
    return logging.getLogger(name)
