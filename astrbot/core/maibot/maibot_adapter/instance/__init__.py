"""
MaiBot 实例管理模块

提供实例模型和管理器
"""

from .model import MaibotInstance, InstanceStatus
from .manager import (
    MaibotInstanceManager,
    initialize_instance_manager,
    get_instance_manager,
    start_maibot,
    stop_maibot,
    list_instances,
    get_instance_status,
    send_message_to_instance,
)

__all__ = [
    # 模型
    "MaibotInstance",
    "InstanceStatus",
    # 管理器
    "MaibotInstanceManager",
    "initialize_instance_manager",
    "get_instance_manager",
    # 便捷函数
    "start_maibot",
    "stop_maibot",
    "list_instances",
    "get_instance_status",
    "send_message_to_instance",
]
