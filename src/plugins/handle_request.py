"""
处理玩家互动的事件处理
功能：
- 请求传送承接。自动识别tpa中文版与英文版
"""
from src.core.events import ChatMessage
from src.core.plugin import Plugin


class Handle_Request_Plugin(Plugin):
    name = "handle_request"

    def setup(self) -> None:
        self.on(ChatMessage, self.handle_msg)
    
    def handle_msg(self,event:ChatMessage):
        event_message:str = event.text
        sender = event.sender or "朋友"
        if event_message.startswith('选项：[✔ 接受][❌ 拒绝]') or event_message.startswith('Options:[✔ Accept…][❌ Decline…]'):
            self.bot.chat('/tpaccept')
            self.bot.chat(f"/m 你好 {sender}，我已接受传送请求。向着星辰与深渊！欢迎来到冒险家协会总部。这里是-->云岫-外交公馆<--")

        


