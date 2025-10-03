from astrbot.api.star import Context, Star, register
@register("astrbot_plugin_meshbot", "xiewoc", "一个MeshBot适配器", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        from .meshbot_adapter import MeshBotPlatformAdapter # noqa