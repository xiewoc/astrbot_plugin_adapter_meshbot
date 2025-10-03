import asyncio
import time

from astrbot.api.platform import Platform, AstrBotMessage, MessageMember, PlatformMetadata, MessageType
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain
from astrbot.core.platform.astr_message_event import MessageSesion
from astrbot.api.platform import register_platform_adapter
from astrbot import logger

for attr_name, getter in [
    ('__iter__', lambda self: iter(self.chain)),
    ('__len__', lambda self: len(self.chain)),
    ('__getitem__', lambda self, index: self.chain[index])
]:
    if not hasattr(MessageChain, attr_name):
        setattr(MessageChain, attr_name, getter)
# Monky Patch

# 导入WebSocket服务器
from .meshbot_ws_server import WebSocketServer, EventType, ClientInfo, MessageContext
from .meshbot_event import MeshBotPlatformEvent


@register_platform_adapter("MeshBot", "MeshBot 适配器", default_config_tmpl={
    "host": "localhost",
    "port": 9238
})
class MeshBotPlatformAdapter(Platform):

    def __init__(self, platform_config: dict, platform_settings: dict, event_queue: asyncio.Queue) -> None:
        super().__init__(event_queue)
        self.config = platform_config
        self.settings = platform_settings
        self.server = None
        self.client_id = None

    async def send_by_session(self, session: MessageSesion, message_chain: MessageChain):
        # 通过会话中保存的client（WebSocketServer实例）来发送消息
        message_data = {
            "type": "chat",
            "message": self._message_chain_to_text(message_chain),
            "timestamp": time.time(),
            "from_bot": True
        }
        # 使用session.client发送给指定客户端
        await session.client.send_to_client(session.session_id, message_data)

    def _message_chain_to_text(self, message_chain: MessageChain) -> str:
        """将消息链转换为纯文本，兼容 MessageChain 或普通可迭代对象"""
        text_parts = []
        # 支持直接可迭代对象或者具有 .chain 属性的对象
        if hasattr(message_chain, '__iter__') and not isinstance(message_chain, str):
            iterable = message_chain
        elif hasattr(message_chain, 'chain'):
            iterable = message_chain.chain
        else:
            return str(message_chain)

        for component in iterable:
            if hasattr(component, 'text'):
                text_parts.append(component.text)
        return ''.join(text_parts)

    def meta(self) -> PlatformMetadata:
        """返回平台元数据"""
        return PlatformMetadata(
            "MeshBot",
            "MeshBot WebSocket 适配器",
        )

    async def run(self):
        host = self.config.get('host', 'localhost')
        port = self.config.get('port', 9238)
        self.server = WebSocketServer(host, port)
        self._setup_event_handlers()
        logger.info(f"MeshBot WebSocket服务器启动在 {host}:{port}")
        # 启动服务器并保持运行
        await self.server.start()

    def _setup_event_handlers(self):
        """设置事件处理器"""
        # 使用lambda函数正确绑定参数
        self.server.on(EventType.CONNECT, 
                      lambda client_info: self._on_client_connect(client_info))
        self.server.on(EventType.DISCONNECT, 
                      lambda client_info: self._on_client_disconnect(client_info))
        self.server.on(EventType.MESSAGE, 
                      lambda context, client_info: self._on_message(context, client_info))
        self.server.on(EventType.CHAT, 
                      lambda context, client_info: self._on_chat_message(context, client_info))
        self.server.on(EventType.ERROR, 
                      lambda client_info, error: self._on_error(client_info, error))

    async def _on_client_connect(self, client_info: ClientInfo):
        """客户端连接事件"""
        logger.info(f"客户端连接: {client_info.id}")

    async def _on_client_disconnect(self, client_info: ClientInfo):
        """客户端断开事件"""
        logger.info(f"客户端断开: {client_info.id}")

    async def _on_message(self, context: MessageContext, client_info: ClientInfo):
        """通用消息处理"""
        logger.info(f"收到消息类型: {context.message_type}")
        
        if context.message_type == "ping":
            pong_msg = {
                "type": "pong", 
                "timestamp": time.time()
            }
            await self.server.send_to_client(client_info.id, pong_msg)

    async def _on_chat_message(self, context: MessageContext, client_info: ClientInfo):
        """聊天消息处理"""
        user = context.data.get("user", "匿名用户")
        message = context.data.get("message", "")
        user_id = context.data.get("user_id", client_info.id)
        request_id = context.data.get("request_id", "")
        self.client_id = client_info.id
        
        logger.info(f"聊天消息: {user} 说: {message}")
        
        # 转换为 AstrBotMessage
        message_data = {
            "type": "chat",
            "user": user,
            "message": message,
            "user_id": user_id,
            #"client_id": client_info.id,
            "client_id": user,
            "timestamp": context.timestamp,
            "message_id": request_id,
            "bot_id": "meshbot_server"
        }
        
        try:
            abm = await self.convert_message(message_data)
            await self.handle_msg(abm)
        except Exception as e:
            logger.error(f"处理聊天消息时出错: {e}")

    async def _on_error(self, client_info: ClientInfo, error: Exception):
        """错误处理"""
        logger.error(f"客户端 {client_info.id} 错误: {error}")

    async def convert_message(self, data: dict) -> AstrBotMessage:
        abm = AstrBotMessage()
        abm.type = MessageType.FRIEND_MESSAGE
        abm.message_str = data.get('message', '')
        
        user_id = data.get('user_id', data.get('client_id', 'unknown'))
        nickname = data.get('user', '匿名用户')
        abm.sender = MessageMember(user_id=user_id, nickname=nickname)
        
        message_content = data.get('message', '')

        abm.message = MessageChain()
        abm.message.chain = [Plain(text=message_content)]

        abm.raw_message = data
        abm.self_id = data.get('bot_id', 'meshbot_server')
        abm.session_id = data.get('client_id', user_id)
        abm.message_id = data.get('message_id', f"msg_{int(time.time() * 1000)}")
        
        return abm

    async def handle_msg(self, message: AstrBotMessage):
        try:
            message_session = MeshBotPlatformEvent(
                message_str=message.message_str,
                message_obj=message,
                platform_meta=self.meta(),
                session_id=message.session_id,
                client=self.server,  # 确保将server实例传递给会话
                msg_id = message.message_id,
                client_id=self.client_id
            )
            self.commit_event(message_session)
        except Exception as e:
            logger.error(f"处理消息时出错: {e}")

    async def stop(self):
        """停止服务器"""
        if self.server:
            await self.server.stop()
        logger.info("MeshBot平台适配器已停止")