import asyncio
import websockets
import json
import time
from typing import Dict, Callable, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

# 导入logger
from astrbot import logger


class EventType(Enum):
    """事件类型枚举"""
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    MESSAGE = "message"
    CHAT = "chat"
    ERROR = "error"


@dataclass
class ClientInfo:
    """客户端信息"""
    id: str
    websocket: Any
    ip: str
    port: int
    connect_time: float


@dataclass
class MessageContext:
    """消息上下文"""
    client_id: str
    data: Dict
    raw_message: str
    timestamp: float
    message_type: str = "unknown"


class WebSocketServer:
    """
    WebSocket服务器类
    """
    
    def __init__(self, host: str = "0.0.0.0", port: int = 9238):
        self.host = host
        self.port = port
        self.connected_clients: Dict[str, ClientInfo] = {}
        self._event_handlers: Dict[EventType, List[Callable]] = {}
        self._server = None
        
    def on(self, event_type: EventType, handler: Callable):
        """注册事件处理器"""
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)
    
    async def _emit(self, event_type: EventType, *args):
        """触发事件"""
        if event_type not in self._event_handlers:
            return
        
        for handler in self._event_handlers[event_type]:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(*args)  # 这里添加了 await
                else:
                    await handler(*args)
            except Exception as e:
                logger.error(f"事件处理器执行出错 {event_type.value}: {e}")
    
    async def start(self):
        """启动服务器"""
        logger.info(f"WebSocket服务器启动在 {self.host}:{self.port}")
        
        # 直接传递方法，websockets 库会自动处理参数
        self._server = await websockets.serve(
            self._handle_connection,  # 直接传递方法
            self.host, 
            self.port
        )
        
        # 保持服务器运行
        await self._server.wait_closed()
    
    async def _handle_connection(self, websocket):
        """处理客户端连接"""
        client_id = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        client_info = ClientInfo(
            id=client_id,
            websocket=websocket,
            ip=websocket.remote_address[0],
            port=websocket.remote_address[1],
            connect_time=time.time()
        )
        
        self.connected_clients[client_id] = client_info
        logger.info(f"客户端连接: {client_id}")
        
        # 触发连接事件
        await self._emit(EventType.CONNECT, client_info)
        
        try:
            async for message in websocket:
                await self._handle_message(client_info, message)
                
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"客户端断开连接: {client_id}")
        except Exception as e:
            logger.error(f"处理连接时出错 {client_id}: {e}")
            await self._emit(EventType.ERROR, client_info, e)
        finally:
            # 清理连接
            self.connected_clients.pop(client_id, None)
            await self._emit(EventType.DISCONNECT, client_info)
            logger.info(f"客户端清理完成: {client_id}")
    
    async def _handle_message(self, client_info: ClientInfo, message: str):
        """处理客户端消息"""
        try:
            # 解析消息
            if isinstance(message, bytes):
                message = message.decode('utf-8')
            
            data = json.loads(message)
            logger.info(f"收到来自 {client_info.id} 的消息: {data}")
            
            # 创建消息上下文
            context = MessageContext(
                client_id=client_info.id,
                data=data,
                raw_message=message,
                timestamp=time.time(),
                message_type=data.get("type", "unknown")
            )
            
            # 触发通用消息事件
            await self._emit(EventType.MESSAGE, context, client_info)
            
            # 特定类型消息处理
            message_type = data.get("type", "").lower()
            if message_type == "chat":
                await self._emit(EventType.CHAT, context, client_info)
            
        except json.JSONDecodeError as e:
            error_response = self._create_error_response("无效的JSON格式")
            await self.send_to_client(client_info.id, error_response)
        except Exception as e:
            logger.error(f"处理消息时出错: {e}")
            error_response = self._create_error_response(f"处理消息失败: {str(e)}")
            await self.send_to_client(client_info.id, error_response)
    
    async def send_to_client(self, client_id: str, message: Dict) -> bool:
        """发送消息给特定客户端"""
        if client_id not in self.connected_clients:
            logger.warning(f"未找到客户端: {client_id}")
            return False
        
        client_info = self.connected_clients[client_id]
        
        try:
            await client_info.websocket.send(json.dumps(message))
            logger.info(f"发送消息给 {client_id}: {message}")
            return True
            
        except websockets.exceptions.ConnectionClosed:
            logger.warning(f"客户端已断开: {client_id}")
            self.connected_clients.pop(client_id, None)
            return False
        except Exception as e:
            logger.error(f"发送消息给 {client_id} 时出错: {e}")
            return False
    
    async def broadcast(self, message: Dict, exclude_client_ids: List[str] = None):
        """广播消息给所有客户端"""
        if not self.connected_clients:
            return
        
        exclude_client_ids = exclude_client_ids or []
        
        for client_id, client_info in list(self.connected_clients.items()):
            if client_id in exclude_client_ids:
                continue
                
            try:
                await self.send_to_client(client_id, message)
            except Exception as e:
                logger.error(f"广播消息给 {client_id} 时出错: {e}")
        
        logger.info(f"广播消息给 {len(self.connected_clients)} 个客户端: {message}")
    
    def _create_error_response(self, message: str) -> Dict:
        """创建错误响应"""
        return {
            "type": "error",
            "message": message,
            "timestamp": time.time()
        }
    
    async def stop(self):
        """停止服务器"""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("服务器已停止")