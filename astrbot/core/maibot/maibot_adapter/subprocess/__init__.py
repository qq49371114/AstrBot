"""
MaiBot 子进程模块

提供子进程入口和日志系统
"""

from .entry import subprocess_main
from .logger import (
    initialize_maibot_logger,
    get_maibot_logger,
    get_logger,
    set_log_publisher,
    is_subprocess_mode,
    _mark_subprocess_mode,
    InstanceLogManager,
)

__all__ = [
    # 入口
    "subprocess_main",
    # 日志
    "initialize_maibot_logger",
    "get_maibot_logger",
    "get_logger",
    "set_log_publisher",
    "is_subprocess_mode",
    "_mark_subprocess_mode",
    "InstanceLogManager",
]
