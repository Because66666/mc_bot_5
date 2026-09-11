# mc_bot_5

基于 [pyCraft](https://github.com/Because66666/pyCraft) 的 Minecraft 机器人，插件化架构。核心是一条单向事件流水线：

```
服务器 → [pyCraft 网络线程] → bridge(协议包 → 事件) → EventBus → 各插件
服务器 ← [网络线程 write_packet] ← bot.chat / send_server_command
```

## 运行

```bat
pip install pycraft-minecraft
set ADDRESS=localhost
set PLAYERNAME=your_account_email@mail.com
python.exe main.py
```

注意，当`PLAYERNAME`为邮箱地址（字段中包含`@`）时，自动使用正版登录，否则使用离线登录。
使用`pip install pycraft-minecraft`安装库后，可用`minecraft`进行调用。
首次运行会打印设备码授权链接，浏览器打开并输入验证码；之后复用缓存令牌。
游戏内其他玩家发 `!hello` 机器人会回复；`!help` 列出全部指令。Ctrl+C 优雅退出。

## 目录结构

```
main.py                  # 组装根：创建 Bot → 注册插件 → run（加功能在这里加一行）
config.py                # 账号 / 服务器地址 / 指令前缀等常量
src/core/events.py       # EventBus + 全部事件定义
src/core/state.py        # bot.state 状态快照（实时坐标/血量/世界）
src/core/bridge.py       # 协议包 → 事件 映射表（接新包只改这里）
src/core/commands.py     # 聊天指令系统（!前缀）
src/core/plugin.py       # Plugin 基类 + PluginManager
src/core/bot.py          # Bot 门面：发送 API、生命周期
src/plugins/             # 功能插件，一个文件一个功能
```

## 内置插件

| 插件 | 功能 |
|---|---|
| `hello` | 示例模板：`!hello` 指令 → 机器人回复 |
| `console_echo` | 把关键事件回显到控制台（纯展示，注释掉注册即关闭） |
| `state_tracker` | 把事件回填到 `bot.state`（位置/血量/世界的唯一写者） |
| `auto_respawn` | 死亡后自动重生 |
| `handle_request` | 自动承接其他玩家的 tpa 传送请求（中英文版均支持） |
| `home_schedule` | 按时间表自动 `/home` 到对应家园点 |

---

## 指南：注册新的事件-响应功能

> 需求场景：**服务器发生了某件事，我的插件要自动做出反应**。按下面三步走。

### 第 1 步：写插件文件

在 `src/plugins/` 新建一个文件，继承 `Plugin`，在 `setup()` 里用 `self.on(事件, 回调)` 订阅：

```python
# src/plugins/low_health.py
from src.core.events import HealthUpdated
from src.core.plugin import Plugin


class LowHealthPlugin(Plugin):
    name = "low_health"

    def setup(self) -> None:
        self.on(HealthUpdated, self._on_health)

    def _on_health(self, event: HealthUpdated) -> None:
        if event.health is not None and event.health < 6:
            self.bot.chat("我快没了，谁来救一下！")
```

### 第 2 步：在 main.py 启用

```python
bot.plugins.register(LowHealthPlugin)   # 加这一行
```

不想用了就注释掉，或注册时传 `enabled=False`——插件注销时订阅自动退订，无需手动清理。

完成。这就是全部流程：**写插件文件 + main.py 注册一行**。

### 第 3 步（可选）：响应一个"还没有事件"的协议包

内置事件来自 9 种常用协议包（聊天、进服、切维度、传送、血量、阵亡、被踢）。如果你想
响应的包还没有事件，去 [bridge.py](file:///d:/python/mc_bot_5/src/core/bridge.py) 的
`_PACKET_EVENT_MAP` 加一行映射——这是全项目唯一与 pyCraft 包类型耦合的地方：

```python
# 1. 定义事件（src/core/events.py 里加 dataclass）
@dataclass
class BlockBroken:
    location: tuple[int, int, int]

# 2. 写事件工厂（bridge.py）：包 → 事件
def _make_block_broken(packet) -> BlockBroken:
    pos = packet.location
    return BlockBroken(location=(pos.x, pos.y, pos.z))

# 3. 登记映射（bridge.py 的 _PACKET_EVENT_MAP）
play.BlockChangePacket: _make_block_broken,
```

之后插件里 `self.on(BlockBroken, ...)` 即可。个别特殊需求也可以跳过事件层，
在插件里直接用 `connection.listener(...)` 监听原始包（逃生舱口，不建议常用）。

---

## 内置事件速查

| 事件 | 触发时机 | 关键字段 |
|---|---|---|
| `ChatMessage` | 收到任何聊天 | `text`（发言内容）、`sender`（玩家名，系统消息为 None）、`sender_uuid`、`source` |
| `JoinedGame` | 进入游戏世界 | `entity_id`、`world_name`、`dimension`、`game_mode`、`world_names` |
| `WorldChanged` | 重生 / 切换维度 | `world_name`、`dimension`、`game_mode` |
| `PositionUpdated` | 服务器传送/校正位置 | `x` `y` `z` `yaw` `pitch` |
| `HealthUpdated` | 生命/饥饿变化 | `health`、`food`、`saturation` |
| `Kicked` | 被服务器断开 | `reason` |

各包字段的详细提取逻辑见 [bridge.py](file:///d:/python/mc_bot_5/src/core/bridge.py)。

## 注册聊天指令

插件里两种写法等价：

```python
def setup(self) -> None:
    # 装饰器写法
    self.bot.commands.command("date", "报时")(self._date)
    # 或函数式写法
    self.bot.commands.register("ping", self._ping, "测试连通")

def _date(self, ctx) -> None:
    # ctx.sender: 发言玩家名（系统消息为 None）；ctx.args: 参数列表
    # ctx.bot: Bot 门面
    self.bot.chat(f"现在是 {time.strftime('%H:%M')}, {ctx.sender}")
```

游戏里发 `!date` 触发；`!help` 自动列出所有指令。机器人自己发的消息不含
`!` 前缀，不会误触发自己。

## Bot API 一览（插件里通过 self.bot / ctx.bot 使用）

| 属性/方法 | 说明 |
|---|---|
| `bot.chat(text)` | 发普通聊天（超 256 字符自动截断），未连接返回 False |
| `bot.send_server_command(cmd)` | 发服务器命令，自动去前导 `/` |
| `bot.respawn()` | 死亡后请求重生 |
| `bot.state` | 实时状态快照：`position` / `health` / `food` / `world.world_name` 等 |
| `bot.events.on(事件, 回调)` | 裸订阅总线（插件内请用 `self.on`，可自动退订） |
| `bot.commands` | 指令注册表 |
| `bot.request_stop()` | 请求程序退出（回调内唯一合法的停止方式） |

## 铁律（违反会断线 / 被服务器踢）

1. **所有事件回调都在 pyCraft 单一网络线程里串行执行**：回调里禁止 `sleep`、
   禁止耗时计算，否则收发包卡死，约 30 秒后被踢。耗时任务请另开线程。
2. **回调里禁止调 `bot.stop()` / `connection.disconnect()`**（网络线程内断连有
   重入风险），要退出只能 `bot.request_stop()`。
3. 插件抛出的异常会被 EventBus 隔离（打印 traceback，不断线），但请尽量自己
   处理可预期的错误。
4. 状态用 `bot.state` 读快照即可，它是网络线程单写、无锁安全的。

## 许可证

本项目采用 [CC BY-NC 4.0（署名-非商业性使用 4.0 国际）](https://creativecommons.org/licenses/by-nc/4.0/) 协议开源：

- ✅ 可自由复制、分发、修改、二次开发，需**署名**（注明原作者与本仓库链接）
- ❌ **不得用于商业目的**（非商业性使用）
- 详细条款见 [LICENSE](file:///d:/python/mc_bot_5/LICENSE)

## 辅助开发

本项目架构使用GLM-5.3-Flash辅助开发。