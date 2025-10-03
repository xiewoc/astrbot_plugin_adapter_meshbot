from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.platform import AstrBotMessage, PlatformMetadata
from astrbot.api.message_components import Plain
from .meshbot_ws_server import WebSocketServer
import time


class MeshBotPlatformEvent(AstrMessageEvent):
    def __init__(self, message_str: str, message_obj: AstrBotMessage, platform_meta: PlatformMetadata, session_id: str, client: WebSocketServer, msg_id: str, client_id: str):
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.client = client
        self.msg_id = msg_id
        self.client_id = client_id
        
    async def send(self, message: MessageChain):
        """发送消息到消息平台"""
        # 遍历消息链
        for component in message.chain:
            if isinstance(component, Plain):  # 文字消息
                await self.client.send_to_client(
                    client_id=self.client_id, 
                    message={
                        "type": "chat",
                        "message": component.text,
                        "timestamp": time.time(),
                        "from_bot": True,
                        "request_id": self.msg_id
                    }
                )

        # 重要：必须调用父类的 send 方法
        await super().send(message)