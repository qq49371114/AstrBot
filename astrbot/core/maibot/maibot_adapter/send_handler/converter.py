"""
MaiBot → AstrBot 消息转换器

将 MaiBot 的 Seg/MessageBase 转换为 AstrBot 的 MessageChain。
"""

from typing import Any, Dict, List, Optional, Union

from astrbot.core.maibot.maim_message import Seg

from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.message.components import (
    Plain,
    Image,
    Record,
    Video,
    Face,
    File,
    Reply,
    At,
)


class MaiBotToAstrBot:
    """MaiBot → AstrBot 消息转换器"""

    @staticmethod
    def convert_segments(segments: List[Dict[str, Any]]) -> MessageChain:
        """
        将消息段字典列表转换为 AstrBot MessageChain

        Args:
            segments: 消息段字典列表，格式: [{"type": "...", "data": ...}, ...]

        Returns:
            MessageChain 对象
        """
        components = []

        for seg in segments:
            component = MaiBotToAstrBot._convert_segment(seg)
            if component:
                components.append(component)

        # 确保至少有一个组件
        if not components:
            components.append(Plain(""))

        return MessageChain(components)

    @staticmethod
    def convert_seg(seg: Seg) -> MessageChain:
        """
        将 Seg 对象转换为 AstrBot MessageChain

        Args:
            seg: MaiBot 的 Seg 对象

        Returns:
            MessageChain 对象
        """
        # 先转换为字典列表
        segments = MaiBotToAstrBot._seg_to_dict_list(seg)
        return MaiBotToAstrBot.convert_segments(segments)

    @staticmethod
    def _seg_to_dict_list(seg: Seg) -> List[Dict[str, Any]]:
        """
        将 Seg 对象转换为字典列表

        Args:
            seg: MaiBot 的 Seg 对象

        Returns:
            消息段字典列表
        """
        result = []

        if seg is None:
            return result

        # 如果是消息段列表
        if seg.type == "seglist":
            if seg.data:
                for sub_seg in seg.data:
                    result.extend(MaiBotToAstrBot._seg_to_dict_list(sub_seg))

        # 如果是转发消息
        elif seg.type == "forward":
            result.append({"type": "text", "data": "[合并转发消息]"})

        # 其他单个消息段
        else:
            result.append({"type": seg.type, "data": seg.data})

        return result

    @staticmethod
    def _convert_segment(seg: Dict[str, Any]) -> Optional[Any]:
        """
        将单个消息段字典转换为 AstrBot 消息组件

        Args:
            seg: 消息段字典，格式: {"type": "...", "data": ...}

        Returns:
            消息组件对象或 None
        """
        seg_type = seg.get("type")
        seg_data = seg.get("data")

        # ========== 文本类型 ==========
        if seg_type == "text":
            return Plain(seg_data) if seg_data else None

        # ========== 图片类型 ==========
        elif seg_type == "image":
            return MaiBotToAstrBot._convert_image(seg_data)

        elif seg_type == "imageurl":
            return Image.fromURL(seg_data) if seg_data else None

        elif seg_type == "emoji":
            return MaiBotToAstrBot._convert_emoji(seg_data)

        # ========== 语音类型 ==========
        elif seg_type == "voice":
            return MaiBotToAstrBot._convert_voice(seg_data)

        elif seg_type == "voiceurl":
            return Record.fromURL(seg_data) if seg_data else None

        # ========== 视频类型 ==========
        elif seg_type == "video":
            return MaiBotToAstrBot._convert_video(seg_data)

        elif seg_type == "videourl":
            return Video.fromURL(seg_data) if seg_data else None

        # ========== QQ 表情 ==========
        elif seg_type == "face":
            if isinstance(seg_data, dict) and "id" in seg_data:
                return Face(id=seg_data["id"])
            elif isinstance(seg_data, int):
                return Face(id=seg_data)
            return None

        # ========== @提及 ==========
        elif seg_type == "at":
            if isinstance(seg_data, dict) and "qq" in seg_data:
                return At(qq=seg_data["qq"])
            return None

        # ========== 文件 ==========
        elif seg_type == "file":
            return MaiBotToAstrBot._convert_file(seg_data)

        # ========== 回复 ==========
        elif seg_type == "reply":
            return MaiBotToAstrBot._convert_reply(seg_data)

        # ========== 未知类型 ==========
        else:
            return Plain(f"[不支持的消息类型: {seg_type}]")

    @staticmethod
    def _convert_image(data: Any) -> Optional[Image]:
        """转换图片消息"""
        if isinstance(data, str):
            # base64 或 URL
            if data.startswith("data:image"):
                # base64 格式
                base64_data = data.split(",", 1)[1] if "," in data else data
                return Image.fromBase64(base64_data)
            elif data.startswith("http"):
                return Image.fromURL(data)
            elif data.startswith("base64://"):
                return Image.fromBase64(data[9:])
            else:
                return Image(file=data)

        elif isinstance(data, dict):
            if "base64" in data:
                return Image.fromBase64(data["base64"])
            elif "url" in data:
                return Image.fromURL(data["url"])
            elif "file" in data:
                return Image(file=data["file"])

        return None

    @staticmethod
    def _convert_emoji(data: Any) -> Optional[Image]:
        """
        转换表情包消息

        支持的格式:
        - 字符串: base64 数据、URL、文件路径
        - 字典: {"base64": ..., "url": ..., "file": ..., "md5": ...}
        """
        if isinstance(data, str):
            if data.startswith("data:image"):
                base64_data = data.split(",", 1)[1] if "," in data else data
                return Image.fromBase64(base64_data)
            elif data.startswith("base64://"):
                return Image.fromBase64(data[9:])
            elif data.startswith("http"):
                return Image.fromURL(data)
            else:
                # 可能是文件路径
                return Image(file=data)

        elif isinstance(data, dict):
            # 优先使用 base64
            if "base64" in data and data["base64"]:
                return Image.fromBase64(data["base64"])
            # 其次使用 URL (包括微信 cdnurl)
            elif "url" in data and data["url"]:
                return Image.fromURL(data["url"])
            elif "cdnurl" in data and data["cdnurl"]:
                return Image.fromURL(data["cdnurl"])
            # 最后使用文件路径
            elif "file" in data and data["file"]:
                return Image(file=data["file"])

        return None

    @staticmethod
    def _convert_voice(data: Any) -> Optional[Record]:
        """转换语音消息"""
        if isinstance(data, str):
            if data.startswith("data:audio"):
                # base64 格式暂不支持
                return None
            elif data.startswith("http"):
                return Record.fromURL(data)
            else:
                return Record(file=data)

        elif isinstance(data, dict):
            if "url" in data:
                return Record.fromURL(data["url"])
            elif "file" in data:
                return Record(file=data["file"])

        return None

    @staticmethod
    def _convert_video(data: Any) -> Optional[Video]:
        """转换视频消息"""
        if isinstance(data, str):
            if data.startswith("data:video"):
                return None
            elif data.startswith("http"):
                return Video.fromURL(data)
            else:
                return Video(file=data)

        elif isinstance(data, dict):
            if "url" in data:
                return Video.fromURL(data["url"])
            elif "file" in data:
                return Video(file=data["file"])

        return None

    @staticmethod
    def _convert_file(data: Any) -> Optional[File]:
        """转换文件消息"""
        if isinstance(data, dict):
            name = data.get("name", "")
            url = data.get("url", "")
            file_path = data.get("file", "")
            return File(name=name, file=file_path, url=url)
        return None

    @staticmethod
    def _convert_reply(data: Any) -> Optional[Reply]:
        """转换回复消息"""
        if isinstance(data, dict):
            reply_id = data.get("id")
            sender = data.get("sender", {})
            sender_id = sender.get("user_id") if isinstance(sender, dict) else None
            sender_nickname = sender.get("nickname") if isinstance(sender, dict) else None

            # 解析消息内容
            message_str = ""
            content = data.get("content")
            if content:
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            message_str += item.get("data", "")
                elif isinstance(content, str):
                    message_str = content

            return Reply(
                id=reply_id,
                sender_id=sender_id,
                sender_nickname=sender_nickname,
                message_str=message_str,
            )

        elif isinstance(data, (int, str)):
            return Reply(id=data)

        return None


# 兼容旧接口
def seg_to_dict_list(segment: Seg) -> List[Dict[str, Any]]:
    """将 Seg 对象转换为字典列表（兼容旧接口）"""
    return MaiBotToAstrBot._seg_to_dict_list(segment)


def convert_maibot_to_astrbot(
    message_segment: Union[Seg, List[Dict[str, Any]]]
) -> MessageChain:
    """将 MaiBot 消息转换为 AstrBot MessageChain（兼容旧接口）"""
    if isinstance(message_segment, list):
        return MaiBotToAstrBot.convert_segments(message_segment)
    return MaiBotToAstrBot.convert_seg(message_segment)
