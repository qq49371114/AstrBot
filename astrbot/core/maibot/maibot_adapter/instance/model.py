"""
MaiBot 单实例模型

定义单个 MaiBot 实例的数据结构和状态
"""

import os
import asyncio
from datetime import datetime
from enum import Enum
from multiprocessing import Process, Queue
from typing import Optional, Dict, Any


class InstanceStatus(str, Enum):
    """实例状态枚举"""
    STOPPED = "stopped"           # 已停止
    STARTING = "starting"         # 启动中
    RUNNING = "running"           # 运行中
    STOPPING = "stopping"         # 停止中
    ERROR = "error"               # 错误状态
    RESTARTING = "restarting"     # 重启中


class MaibotInstance:
    """单个 MaiBot 实例（进程隔离模式）

    每个实例在独立子进程中运行，通过队列进行 IPC 通信
    """

    def __init__(
        self,
        instance_id: str,
        name: str,
        description: str = "",
        is_default: bool = False,
        lifecycle: Optional[Dict[str, Any]] = None,
        logging: Optional[Dict[str, Any]] = None,
        knowledge_base: Optional[Dict[str, Any]] = None,
        host: str = "127.0.0.1",
        port: int = 8000,
        web_host: str = "127.0.0.1",
        web_port: int = 8001,
        enable_webui: bool = False,
        enable_socket: bool = False,
    ):
        # 基本信息
        self.instance_id = instance_id
        self.name = name
        self.description = description
        self.is_default = is_default

        # 生命周期配置
        self.lifecycle = lifecycle or {
            "start_order": 0,           # 启动顺序（数字小的先启动）
            "restart_on_crash": True,   # 崩溃后自动重启
            "max_restarts": 3,          # 最大重启次数
            "restart_delay": 5000,      # 重启延迟（毫秒）
            "auto_start": True,         # AstrBot 启动时是否自动启动此实例
        }

        # 日志配置
        self.logging = logging or {
            "enable_console": False,    # 是否输出到主控制台
            "log_level": "INFO",        # 日志级别
        }

        # 知识库配置（AstrBot 知识库并行检索）
        self.knowledge_base = knowledge_base or {
            "enabled": False,           # 是否启用 AstrBot 知识库
            "kb_names": [],             # 使用的知识库名称列表
            "fusion_top_k": 5,          # 融合后返回的结果数量
            "return_top_k": 20,         # 从知识库检索的结果数量
        }

        # 网络配置
        self.host = host
        self.port = port
        self.web_host = web_host
        self.web_port = web_port
        self.enable_webui = enable_webui
        self.enable_socket = enable_socket

        # 运行时状态（不持久化）
        self.status = InstanceStatus.STOPPED
        self.error_message: Optional[str] = None
        self.created_at: Optional[datetime] = None
        self.updated_at: Optional[datetime] = None
        self.started_at: Optional[datetime] = None

        # 进程隔离相关
        self.process: Optional[Process] = None
        self.input_queue: Optional[Queue] = None   # 主进程 -> 子进程
        self.output_queue: Optional[Queue] = None  # 子进程 -> 主进程
        self.last_heartbeat: Optional[datetime] = None

        # 异步任务
        self._status_monitor_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._message_task: Optional[asyncio.Task] = None

    def get_data_dir(self, base_path: str) -> str:
        """获取实例数据目录"""
        return os.path.join(base_path, "instances", self.instance_id)

    def get_config_path(self, base_path: str) -> str:
        """获取实例配置文件路径"""
        return os.path.join(base_path, "config", "instances", f"{self.instance_id}.toml")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 API 响应）"""
        return {
            "id": self.instance_id,
            "name": self.name,
            "description": self.description,
            "is_default": self.is_default,
            "lifecycle": self.lifecycle,
            "logging": self.logging,
            "knowledge_base": self.knowledge_base,
            "host": self.host,
            "port": self.port,
            "web_host": self.web_host,
            "web_port": self.web_port,
            "enable_webui": self.enable_webui,
            "enable_socket": self.enable_socket,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
        }

    def to_meta_dict(self) -> Dict[str, Any]:
        """转换为元数据字典（用于持久化配置，不含运行时状态）"""
        return {
            "instance_id": self.instance_id,
            "name": self.name,
            "description": self.description,
            "is_default": self.is_default,
            "lifecycle": self.lifecycle,
            "logging": self.logging,
            "knowledge_base": self.knowledge_base,
            "host": self.host,
            "port": self.port,
            "web_host": self.web_host,
            "web_port": self.web_port,
            "enable_webui": self.enable_webui,
            "enable_socket": self.enable_socket,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MaibotInstance":
        """从字典创建实例"""
        instance = cls(
            instance_id=data.get("instance_id", data.get("id", "")),
            name=data.get("name", ""),
            description=data.get("description", ""),
            is_default=data.get("is_default", False),
            lifecycle=data.get("lifecycle"),
            logging=data.get("logging"),
            knowledge_base=data.get("knowledge_base"),
            host=data.get("host", "127.0.0.1"),
            port=data.get("port", 8000),
            web_host=data.get("web_host", "127.0.0.1"),
            web_port=data.get("web_port", 8001),
            enable_webui=data.get("enable_webui", False),
            enable_socket=data.get("enable_socket", False),
        )

        # 恢复时间戳
        if data.get("created_at"):
            try:
                instance.created_at = datetime.fromisoformat(data["created_at"])
            except (ValueError, TypeError):
                pass
        if data.get("updated_at"):
            try:
                instance.updated_at = datetime.fromisoformat(data["updated_at"])
            except (ValueError, TypeError):
                pass

        return instance


__all__ = [
    "InstanceStatus",
    "MaibotInstance",
]
