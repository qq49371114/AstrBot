"""
MaiBot 适配器模块

负责将 AstrBot 的消息格式转换为 MaiBot 的格式，实现消息互通

目录结构：
├── instance/               # 实例管理
│   ├── model.py            # MaibotInstance + InstanceStatus
│   └── manager.py          # MaibotInstanceManager + 便捷函数
│
├── subprocess/             # 子进程相关
│   ├── entry.py            # 子进程入口
│   └── logger.py           # 子进程日志系统
│
├── recv_handler/           # 接收处理（AstrBot → MaiBot）
│   ├── converter.py        # AstrMessage → MessageBase 转换器
│   └── message_handler.py  # 消息接收处理入口
│
├── send_handler/           # 发送处理（MaiBot → AstrBot）
│   ├── converter.py        # MessageBase → MessageChain 转换器
│   └── reply_handler.py    # 回复发送处理入口
│
├── ipc/                    # 进程间通信
│   ├── protocol.py         # 消息协议定义
│   ├── client.py           # 主进程侧（LocalClient）
│   └── server.py           # 子进程侧（LocalServer）
│
└── adapter.py              # 平台适配器（事件存储）
"""

# ========== IPC 模块 ==========
from .ipc import (
    MessageType,
    IPCMessage,
    LocalClient,
    LocalServer,
)

# ========== 接收处理（AstrBot → MaiBot） ==========
from .recv_handler import (
    RecvMessageHandler,
    AstrBotToMaiBot,
)

# ========== 发送处理（MaiBot → AstrBot） ==========
from .send_handler import (
    ReplyHandler,
    create_reply_handler,
    MaiBotToAstrBot,
    seg_to_dict_list,
    convert_maibot_to_astrbot,
)

# ========== 平台适配器 ==========
from .adapter import (
    parse_astrbot_platform,
    parse_astrbot_instance_id,
    AstrBotPlatformAdapter,
    get_astrbot_adapter,
    initialize_adapter,
)

# ========== 实例管理 ==========
from .instance import (
    InstanceStatus,
    MaibotInstance,
    MaibotInstanceManager,
    initialize_instance_manager,
    get_instance_manager,
    start_maibot,
    stop_maibot,
    list_instances,
    get_instance_status,
    send_message_to_instance,
)

# ========== 子进程 ==========
from .subprocess import (
    subprocess_main,
    initialize_maibot_logger,
    get_maibot_logger,
    get_logger,
)

__all__ = [
    # IPC 模块
    "MessageType",
    "IPCMessage",
    "LocalClient",
    "LocalServer",
    # 接收处理
    "RecvMessageHandler",
    "AstrBotToMaiBot",
    # 发送处理
    "ReplyHandler",
    "create_reply_handler",
    "MaiBotToAstrBot",
    "seg_to_dict_list",
    "convert_maibot_to_astrbot",
    # 平台适配器
    "parse_astrbot_platform",
    "parse_astrbot_instance_id",
    "AstrBotPlatformAdapter",
    "get_astrbot_adapter",
    "initialize_adapter",
    # 实例管理
    "InstanceStatus",
    "MaibotInstance",
    "MaibotInstanceManager",
    "initialize_instance_manager",
    "get_instance_manager",
    "start_maibot",
    "stop_maibot",
    "list_instances",
    "get_instance_status",
    "send_message_to_instance",
    # 子进程
    "subprocess_main",
    "initialize_maibot_logger",
    "get_maibot_logger",
    "get_logger",
]
