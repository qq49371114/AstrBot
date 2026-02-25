"""
MaiBot 实例日志适配器

提供：
1. 实例级别的独立日志目录 (logs/mailog/{instance_id}/)
2. 日志转发到主进程的控制台输出
3. MaiBot 的 get_logger 接口
4. 完全接管子进程的日志配置，避免与主日志系统冲突
"""

import asyncio
import json
import logging
import structlog
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, IO, Callable

# 日志文件 flush 间隔（秒）
FLUSH_INTERVAL = 60

# 全局日志转发回调（用于发送到主进程）
_log_publisher: Optional[Callable] = None

# 子进程模式标志（在导入任何其他模块之前设置）
_subprocess_mode = False


def _mark_subprocess_mode():
    """标记当前进程为子进程模式，用于通知其他日志模块"""
    global _subprocess_mode
    _subprocess_mode = True


def is_subprocess_mode() -> bool:
    """检查是否运行在子进程模式"""
    global _subprocess_mode
    return _subprocess_mode


def set_log_publisher(publisher: Callable):
    """设置日志发布回调，用于发送到主进程"""
    global _log_publisher
    _log_publisher = publisher


class InstanceFileHandler(logging.Handler):
    """实例级别的文件处理器，支持 structlog JSON 输出和定时 flush"""

    def __init__(
        self,
        log_dir: Path,
        level: str = "INFO",
        flush_interval: int = FLUSH_INTERVAL,
    ):
        super().__init__()
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.level = getattr(logging, level.upper(), logging.INFO)
        self.flush_interval = flush_interval

        self._lock = threading.Lock()
        self._last_flush = time.time()
        self._buffer: list[str] = []
        self._current_file: Optional[Path] = None
        self._current_stream: Optional[IO] = None
        self._init_current_file()

    def _init_current_file(self):
        """初始化当前日志文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._current_file = self.log_dir / f"app_{timestamp}.log.jsonl"
        self._current_stream = open(self._current_file, "a", encoding="utf-8")

    def _should_flush(self) -> bool:
        """检查是否需要 flush"""
        return time.time() - self._last_flush >= self.flush_interval

    def _do_flush(self):
        """执行 flush"""
        if self._buffer and self._current_stream:
            for line in self._buffer:
                self._current_stream.write(line + "\n")
            self._current_stream.flush()
            self._buffer.clear()
        self._last_flush = time.time()

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为 JSON 字符串

        处理 structlog 的 event_dict，输出标准的 JSONL 格式
        """
        try:
            # structlog 会将 event_dict 存储在 record.msg 中
            if hasattr(record, 'msg') and isinstance(record.msg, dict):
                event_dict = record.msg.copy()
            else:
                # 非 structlog 的日志，使用 record 的属性构建字典
                event_dict = {
                    "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                    "level": record.levelname.lower(),
                    "logger_name": record.name,
                    "event": record.getMessage(),
                }

            # 确保 timestamp 是 ISO 格式字符串
            if "timestamp" not in event_dict or not event_dict.get("timestamp"):
                event_dict["timestamp"] = datetime.fromtimestamp(record.created).isoformat()

            # 确保 level 存在
            if "level" not in event_dict:
                event_dict["level"] = record.levelname.lower()

            # 转换为 JSON（确保 ASCII=False 以支持中文）
            return json.dumps(event_dict, ensure_ascii=False)

        except (TypeError, ValueError) as e:
            # 如果处理失败，返回包含错误信息的简单 JSON
            return json.dumps({
                "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                "level": record.levelname.lower(),
                "event": f"[日志格式化错误: {e}] {record.getMessage()}",
            }, ensure_ascii=False)

    def emit(self, record: logging.LogRecord):
        """发出日志记录"""
        try:
            msg = self.format(record)
            with self._lock:
                # 检查是否需要 flush
                if self._should_flush():
                    self._do_flush()

                # 写入缓冲区
                self._buffer.append(msg)

                # 如果缓冲区太大，也 flush
                if len(self._buffer) >= 100:
                    self._do_flush()

        except Exception:
            self.handleError(record)

    def flush(self):
        """手动 flush"""
        with self._lock:
            self._do_flush()

    def close(self):
        """关闭处理器"""
        with self._lock:
            self._do_flush()
            if self._current_stream:
                self._current_stream.close()
                self._current_stream = None
        super().close()


class MaiBotLogHandler(logging.Handler):
    """MaiBot 日志处理器

    接收 MaiBot 的日志消息，转发到 maibot_logger 处理
    """

    def __init__(self, instance_id: str):
        super().__init__()
        self.instance_id = instance_id

    def emit(self, record: logging.LogRecord):
        """发送日志到 maibot_logger"""
        try:
            # 获取格式化后的消息
            msg = self.format(record)

            # 获取日志级别
            level = record.levelname.lower()
            if level not in ("debug", "info", "warning", "error", "critical"):
                level = "info"

            # 如果设置了发布回调，发送到主进程
            if _log_publisher:
                try:
                    _log_publisher(level, msg)
                except Exception:
                    pass

        except Exception:
            self.handleError(record)


class InstanceLogManager:
    """实例日志管理器

    每个子进程创建一个实例，用于管理该实例的日志输出
    """

    _instances: Dict[str, "InstanceLogManager"] = {}
    _lock = threading.Lock()

    def __init__(
        self,
        instance_id: str,
        log_level: str = "INFO",
        enable_console: bool = True,
        base_log_dir: Path = Path("logs/mailog"),
    ):
        """
        初始化实例日志管理器

        Args:
            instance_id: 实例ID
            log_level: 日志级别
            enable_console: 是否发送到主进程（通过 output_queue）
            base_log_dir: 日志基础目录
        """
        self.instance_id = instance_id
        self.log_level = log_level
        self.enable_console = enable_console
        self.base_log_dir = base_log_dir

        # 实例日志目录
        self.log_dir = self.base_log_dir / instance_id
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # 文件处理器
        self._file_handler = InstanceFileHandler(
            log_dir=self.log_dir,
            level=log_level,
            flush_interval=FLUSH_INTERVAL,
        )

        # MaiBot 日志处理器
        self._maibot_handler = MaiBotLogHandler(instance_id)

        # 缓存的日志条目（用于发送到主进程）
        self._log_buffer: list[Dict[str, Any]] = []
        self._log_buffer_lock = asyncio.Lock()

        # 注册到全局字典
        with InstanceLogManager._lock:
            InstanceLogManager._instances[instance_id] = self

        # 配置日志系统
        self._setup_logging()

    def _setup_logging(self):
        """配置日志系统

        设置 MaiBot 的 logger，将日志写入文件并转发到主进程
        """
        # 配置 structlog
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.CallsiteParameterAdder(
                    parameters=[
                        structlog.processors.CallsiteParameter.PATHNAME,
                        structlog.processors.CallsiteParameter.LINENO,
                    ]
                ),
                structlog.processors.StackInfoRenderer(),
                structlog.dev.set_exc_info,
                structlog.processors.TimeStamper(fmt="%H:%M:%S", utc=False),
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        # 获取根 logger
        root_logger = logging.getLogger()

        # 设置根日志器级别为 DEBUG，确保所有日志都能被处理
        root_logger.setLevel(logging.DEBUG)

        # 清除所有现有的 handlers
        for handler in root_logger.handlers[:]:
            handler.close()
            root_logger.removeHandler(handler)

        # 添加文件处理器（按配置的级别过滤）
        file_level = getattr(logging, self.log_level.upper(), logging.INFO)
        self._file_handler.setLevel(file_level)
        root_logger.addHandler(self._file_handler)

        # 添加 MaiBot 日志处理器（用于发送到主进程）
        if self.enable_console:
            # 设置为 DEBUG，确保能接收所有级别日志
            self._maibot_handler.setLevel(logging.DEBUG)
            # 设置纯文本格式化器（不包含 ANSI 颜色代码）
            console_formatter = structlog.stdlib.ProcessorFormatter(
                processor=structlog.dev.ConsoleRenderer(colors=False),
                foreign_pre_chain=[
                    structlog.stdlib.add_logger_name,
                    structlog.stdlib.add_log_level,
                    structlog.processors.TimeStamper(fmt="%H:%M:%S", utc=False),
                    structlog.processors.format_exc_info,
                ],
            )
            self._maibot_handler.setFormatter(console_formatter)
            root_logger.addHandler(self._maibot_handler)

        # 注意：InstanceFileHandler 使用自定义的 format() 方法输出 JSON
        # 不需要设置 file_formatter

    def publish_log(self, level: str, message: str, extra: Optional[Dict] = None):
        """
        发布日志（发送到主进程）

        Args:
            level: 日志级别
            message: 日志消息
            extra: 额外信息
        """
        if not self.enable_console:
            return

        log_entry = {
            "level": level,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "instance_id": self.instance_id,
        }
        if extra:
            log_entry.update(extra)

        # 发送到主进程
        if _log_publisher:
            try:
                _log_publisher(level, message)
            except Exception:
                pass

    async def get_logs_for_mainprocess(self) -> list[Dict[str, Any]]:
        """获取待发送到主进程的日志"""
        async with self._log_buffer_lock:
            logs = self._log_buffer.copy()
            self._log_buffer.clear()
        return logs

    def flush(self):
        """Flush 文件处理器"""
        self._file_handler.flush()

    def shutdown(self):
        """关闭日志管理器"""
        self.flush()
        self._file_handler.close()

    @classmethod
    def get_instance(cls, instance_id: str) -> Optional["InstanceLogManager"]:
        """获取指定实例的日志管理器"""
        return cls._instances.get(instance_id)

    @classmethod
    def cleanup(cls, instance_id: str):
        """清理指定实例的日志管理器"""
        with cls._lock:
            manager = cls._instances.pop(instance_id, None)
            if manager:
                manager.flush()


# 全局日志管理器实例
_maibot_logger: Optional[InstanceLogManager] = None


def initialize_maibot_logger(
    instance_id: str,
    log_level: str = "INFO",
    enable_console: bool = True,
    log_publisher: Optional[Callable] = None,
) -> InstanceLogManager:
    """
    初始化 MaiBot 日志系统

    Args:
        instance_id: 实例ID
        log_level: 日志级别
        enable_console: 是否输出到主进程控制台
        log_publisher: 日志发布回调，用于发送到主进程

    Returns:
        InstanceLogManager 实例
    """
    global _maibot_logger, _log_publisher

    # 标记子进程模式，通知其他日志模块
    _mark_subprocess_mode()

    if log_publisher:
        _log_publisher = log_publisher

    _maibot_logger = InstanceLogManager(
        instance_id=instance_id,
        log_level=log_level,
        enable_console=enable_console,
    )
    return _maibot_logger


def get_maibot_logger() -> Optional[InstanceLogManager]:
    """获取 MaiBot 日志管理器"""
    return _maibot_logger


def get_logger(name: Optional[str] = None):
    """
    获取 MaiBot logger

    Args:
        name: logger 名称

    Returns:
        structlog logger
    """
    if _maibot_logger is None:
        # 如果还没初始化，返回默认 logger（不会发送到主进程）
        return structlog.get_logger(name)

    return structlog.get_logger(name).bind(logger_name=name or "maibot")


# 导出
__all__ = [
    "initialize_maibot_logger",
    "get_maibot_logger",
    "get_logger",
    "InstanceLogManager",
    "set_log_publisher",
    "_mark_subprocess_mode",
    "is_subprocess_mode",
]
