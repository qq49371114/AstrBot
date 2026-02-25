"""
MaiBot 多实例启动管理器

通过实例ID启动和管理多个 MaiBot 实例
支持进程隔离，每个实例在独立子进程中运行
配置从 data/maibot/config/instances_meta.json 读取
数据存储到 data/maibot/instances/{instance_id}
"""

import asyncio
import json
import os
import shutil
import sys
import time
from datetime import datetime
from multiprocessing import Process, Queue
from typing import Optional, Dict, Any, List

# 确保项目根目录在路径中（Windows multiprocessing 需要）
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from astrbot.core.maibot.maibot_adapter.subprocess.entry import subprocess_main
from astrbot.core.log import LogManager

# 使用 AstrBot 的日志系统，避免与 MaiBot 的 structlog 冲突
logger = LogManager.GetLogger("maibot_instance")

# 心跳超时时间（秒）
HEARTBEAT_TIMEOUT = 30


# 先导入 model 中的类
from .model import MaibotInstance, InstanceStatus


class MaibotInstanceManager:
    """MaiBot 多实例管理器"""

    def __init__(self, data_root: str = "data/maibot"):
        self.data_root = data_root
        self.instances: Dict[str, MaibotInstance] = {}
        self.metadata_path = os.path.join(data_root, "config", "instances_meta.json")
        self._astrbot_context = None  # AstrBot Context 引用，用于知识库 IPC

    async def initialize(self) -> None:
        """初始化实例管理器"""
        os.makedirs(os.path.join(self.data_root, "config", "instances"), exist_ok=True)
        os.makedirs(os.path.join(self.data_root, "instances"), exist_ok=True)

        await self._load_instances_metadata()

        if "default" not in self.instances:
            logger.info("默认实例不存在，正在创建...")
            await self.create_instance("default", "默认麦麦", is_default=True)

        logger.info(f"实例管理器初始化完成，共 {len(self.instances)} 个实例")

    async def _load_instances_metadata(self) -> None:
        """加载实例元数据"""
        if not os.path.exists(self.metadata_path):
            logger.info("未找到实例元数据文件")
            return

        with open(self.metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        # 默认配置模板
        default_lifecycle = {
            "start_order": 0,
            "restart_on_crash": True,
            "max_restarts": 3,
            "restart_delay": 5000,
        }
        default_logging = {
            "enable_console": True,
            "log_level": "INFO",
        }
        default_knowledge_base = {
            "enabled": False,
            "kb_names": [],
            "fusion_top_k": 5,
            "return_top_k": 20,
        }

        needs_save = False
        updated_instances = []

        for instance_data in metadata.get("instances", []):
            instance_id = instance_data.get("id", "unknown")
            updated = False

            # 自动填充缺失的字段
            lifecycle = instance_data.get("lifecycle")
            if lifecycle is None:
                lifecycle = default_lifecycle.copy()
                instance_data["lifecycle"] = lifecycle
                updated = True
            else:
                for key, value in default_lifecycle.items():
                    if key not in lifecycle:
                        lifecycle[key] = value
                        updated = True

            logging_config = instance_data.get("logging")
            if logging_config is None:
                logging_config = default_logging.copy()
                instance_data["logging"] = logging_config
                updated = True
            else:
                for key, value in default_logging.items():
                    if key not in logging_config:
                        logging_config[key] = value
                        updated = True

            knowledge_base_config = instance_data.get("knowledge_base")
            if knowledge_base_config is None:
                knowledge_base_config = default_knowledge_base.copy()
                instance_data["knowledge_base"] = knowledge_base_config
                updated = True
            else:
                for key, value in default_knowledge_base.items():
                    if key not in knowledge_base_config:
                        knowledge_base_config[key] = value
                        updated = True

            if updated:
                updated_instances.append(instance_id)
                needs_save = True

            instance = MaibotInstance(
                instance_id=instance_id,
                name=instance_data["name"],
                description=instance_data.get("description", ""),
                is_default=instance_data.get("is_default", False),
                lifecycle=lifecycle,
                logging=logging_config,
                knowledge_base=knowledge_base_config,
                host=instance_data.get("host", "127.0.0.1"),
                port=instance_data.get("port", 8000),
                web_host=instance_data.get("web_host", "127.0.0.1"),
                web_port=instance_data.get("web_port", 8001),
                enable_webui=instance_data.get("enable_webui", False),
                enable_socket=instance_data.get("enable_socket", False),
            )
            if instance_data.get("created_at"):
                instance.created_at = datetime.fromisoformat(instance_data["created_at"])
            if instance_data.get("updated_at"):
                instance.updated_at = datetime.fromisoformat(instance_data["updated_at"])
            self.instances[instance.instance_id] = instance

        # 如果有字段被自动填充，热更新配置文件
        if needs_save:
            logger.info(f"检测到 {len(updated_instances)} 个实例缺少配置字段，正在自动填充...")
            metadata["instances"] = [
                {
                    "id": inst.instance_id,
                    "name": inst.name,
                    "description": inst.description,
                    "is_default": inst.is_default,
                    "lifecycle": inst.lifecycle,
                    "logging": inst.logging,
                    "knowledge_base": inst.knowledge_base,
                    "host": inst.host,
                    "port": inst.port,
                    "web_host": inst.web_host,
                    "web_port": inst.web_port,
                    "enable_webui": inst.enable_webui,
                    "enable_socket": inst.enable_socket,
                    "created_at": inst.created_at.isoformat() if inst.created_at else None,
                    "updated_at": inst.updated_at.isoformat() if inst.updated_at else None,
                }
                for inst in self.instances.values()
            ]
            metadata["updated_at"] = datetime.now().isoformat()

            os.makedirs(os.path.dirname(self.metadata_path), exist_ok=True)
            with open(self.metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            logger.info(f"已自动更新配置文件: {updated_instances}")

        logger.info(f"已加载 {len(self.instances)} 个实例")

    async def _save_instances_metadata(self) -> None:
        """保存实例元数据"""
        instances_data = [
            {
                "id": inst.instance_id,
                "name": inst.name,
                "description": inst.description,
                "is_default": inst.is_default,
                "lifecycle": inst.lifecycle,
                "logging": inst.logging,
                "knowledge_base": inst.knowledge_base,
                "host": inst.host,
                "port": inst.port,
                "web_host": inst.web_host,
                "web_port": inst.web_port,
                "enable_webui": inst.enable_webui,
                "enable_socket": inst.enable_socket,
                "created_at": inst.created_at.isoformat() if inst.created_at else None,
                "updated_at": inst.updated_at.isoformat() if inst.updated_at else None,
            }
            for inst in self.instances.values()
        ]

        metadata = {
            "version": "1.0",
            "updated_at": datetime.now().isoformat(),
            "instances": instances_data,
        }

        os.makedirs(os.path.dirname(self.metadata_path), exist_ok=True)
        with open(self.metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    async def create_instance(
        self,
        instance_id: str,
        name: str,
        description: str = "",
        is_default: bool = False,
        host: str = "127.0.0.1",
        port: int = 8000,
        web_host: str = "127.0.0.1",
        web_port: int = 8001,
        enable_webui: bool = False,
        enable_socket: bool = False,
        config_updates: Optional[Dict[str, Any]] = None,
    ) -> MaibotInstance:
        """创建新实例

        Args:
            config_updates: 配置修改项（只修改的部分），会与模板配置合并
        """
        if instance_id in self.instances:
            raise ValueError(f"实例ID已存在: {instance_id}")

        instance = MaibotInstance(
            instance_id=instance_id,
            name=name,
            description=description,
            is_default=is_default,
            host=host,
            port=port,
            web_host=web_host,
            web_port=web_port,
            enable_webui=enable_webui,
            enable_socket=enable_socket,
        )

        instance_dir = instance.get_data_dir(self.data_root)
        os.makedirs(os.path.join(instance_dir, "logs"), exist_ok=True)
        os.makedirs(os.path.join(instance_dir, "cache"), exist_ok=True)

        instance.created_at = datetime.now()

        template_path = os.path.join(
            os.path.dirname(__file__),
            "../..",
            "maibot",
            "template",
            "bot_config_template.toml",
        )
        config_path = instance.get_config_path(self.data_root)
        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        if os.path.exists(template_path):
            shutil.copy2(template_path, config_path)
            logger.info(f"已从模板创建实例 {instance_id} 配置文件")
        else:
            logger.warning(f"未找到配置模板: {template_path}")

        # 合并用户修改的配置
        if config_updates:
            try:
                import tomlkit
                # 读取已复制的模板配置
                config_content = ""
                if os.path.exists(config_path):
                    with open(config_path, "r", encoding="utf-8") as f:
                        config_content = f.read()

                config = tomlkit.loads(config_content)

                # 递归合并配置
                def deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
                    result = base.copy()
                    for key, value in updates.items():
                        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                            result[key] = deep_merge(result[key], value)
                        else:
                            result[key] = value
                    return result

                config = deep_merge(dict(config), config_updates)

                # 保存合并后的配置
                with open(config_path, "w", encoding="utf-8") as f:
                    tomlkit.dump(config, f)

                logger.info(f"已合并实例 {instance_id} 的配置修改")
            except Exception as e:
                logger.error(f"合并实例 {instance_id} 配置失败: {e}")

        self.instances[instance_id] = instance
        await self._save_instances_metadata()

        logger.info(f"实例 {instance_id} 创建成功")
        return instance

    async def start_instance(self, instance_id: str) -> bool:
        """启动指定实例（进程隔离模式）"""
        if instance_id not in self.instances:
            logger.error(f"实例不存在: {instance_id}")
            return False

        instance = self.instances[instance_id]

        if instance.status == InstanceStatus.RUNNING:
            logger.warning(f"实例 {instance_id} 已在运行")
            return True

        try:
            instance.status = InstanceStatus.STARTING
            instance.error_message = ""

            # 1. 检查配置文件是否存在
            config_path = instance.get_config_path(self.data_root)
            if not os.path.exists(config_path):
                instance.status = InstanceStatus.STOPPED
                instance.error_message = "配置文件不存在，请先配置实例"
                logger.warning(f"实例 {instance_id} 配置文件不存在: {config_path}")
                return False

            # 2. 创建进程间通信队列
            instance.input_queue = Queue()
            instance.output_queue = Queue()

            # 3. 构建配置字典
            data_root = self.data_root
            config = {
                "data_root": data_root,
                "host": instance.host,
                "port": instance.port,
                "web_host": instance.web_host,
                "web_port": instance.web_port,
                "enable_webui": instance.enable_webui,
                "enable_socket": instance.enable_socket,
                "logging": instance.logging,
                "knowledge_base": instance.knowledge_base,
            }

            # 4. 创建并启动子进程
            logger.info(f"正在启动实例 {instance_id} 的子进程...")
            instance.process = Process(
                target=subprocess_main,
                args=(
                    instance_id,
                    data_root,
                    config,
                    instance.input_queue,
                    instance.output_queue,
                ),
                name=f"MaiBot-{instance_id}",
            )
            instance.process.start()
            logger.info(f"子进程已启动，PID: {instance.process.pid}")

            # 5. 等待子进程初始化并接收初始状态
            init_timeout = 30
            start_time = time.time()

            while time.time() - start_time < init_timeout:
                if instance.output_queue.empty():
                    await asyncio.sleep(0.1)
                    continue

                try:
                    msg = instance.output_queue.get(timeout=1.0)
                    msg_type = msg.get("type", "")
                    payload = msg.get("payload", {})

                    if msg_type == "status":
                        status = payload.get("status", "")
                        message = payload.get("message", "")
                        error = payload.get("error", "")

                        if status == "running":
                            instance.status = InstanceStatus.RUNNING
                            instance.started_at = datetime.now()
                            instance.last_heartbeat = datetime.now()
                            logger.info(f"实例 {instance_id} 启动成功，状态: {message}")
                            instance._status_monitor_task = asyncio.create_task(
                                self._monitor_instance_status(instance)
                            )
                            return True
                        elif status == "error":
                            instance.status = InstanceStatus.ERROR
                            instance.error_message = error or message
                            logger.error(f"实例 {instance_id} 启动失败: {error or message}")
                            self._cleanup_instance(instance)
                            return False
                        elif status == "config_needed":
                            instance.status = InstanceStatus.STOPPED
                            instance.error_message = "配置已创建，请填写后重新启动"
                            logger.info(f"实例 {instance_id} 配置已创建，请填写后重新启动")
                            self._cleanup_instance(instance)
                            return True
                        else:
                            logger.info(f"实例 {instance_id} 状态: {status} - {message}")
                            if status == "initializing":
                                instance.status = InstanceStatus.STARTING
                                continue
                    elif msg_type == "log":
                        level = payload.get("level", "info")
                        msg_text = payload.get("message", "")
                        if level == "error":
                            logger.error(f"[{instance_id}] {msg_text}")
                        elif level == "warning":
                            logger.warning(f"[{instance_id}] {msg_text}")
                        else:
                            logger.info(f"[{instance_id}] {msg_text}")

                except Exception as e:
                    logger.warning(f"解析子进程消息时出错: {e}")
                    continue

            instance.status = InstanceStatus.ERROR
            instance.error_message = "启动超时"
            logger.error(f"实例 {instance_id} 启动超时")
            self._cleanup_instance(instance)
            return False

        except Exception as e:
            instance.status = InstanceStatus.ERROR
            instance.error_message = str(e)
            logger.error(f"实例 {instance_id} 启动失败: {e}", exc_info=True)
            self._cleanup_instance(instance)
            return False

    def _cleanup_instance(self, instance: MaibotInstance) -> None:
        """清理实例资源"""
        if instance.process and instance.process.is_alive():
            instance.process.terminate()
            instance.process.join(timeout=5)
            if instance.process.is_alive():
                instance.process.kill()
            logger.info(f"已终止实例 {instance.instance_id} 的子进程")

        if instance.input_queue:
            try:
                while not instance.input_queue.empty():
                    instance.input_queue.get_nowait()
            except Exception:
                pass

        if instance.output_queue:
            try:
                while not instance.output_queue.empty():
                    instance.output_queue.get_nowait()
            except Exception:
                pass

        if instance._status_monitor_task:
            instance._status_monitor_task.cancel()
        if instance._heartbeat_task:
            instance._heartbeat_task.cancel()
        if instance._message_task:
            instance._message_task.cancel()

        instance.process = None
        instance.input_queue = None
        instance.output_queue = None
        instance._status_monitor_task = None
        instance._heartbeat_task = None
        instance._message_task = None

    async def _monitor_instance_status(self, instance: MaibotInstance) -> None:
        """监控实例状态"""
        instance_id = instance.instance_id
        restart_count = 0
        max_restarts = instance.lifecycle.get("max_restarts", 3)

        instance._heartbeat_task = asyncio.create_task(self._heartbeat_loop(instance))
        instance._message_task = asyncio.create_task(self._message_loop(instance))

        logger.info(f"实例 {instance_id} 已启动心跳和消息循环")

        try:
            while instance.status == InstanceStatus.RUNNING:
                await asyncio.sleep(1.0)

                if instance.process and not instance.process.is_alive():
                    exit_code = instance.process.exitcode
                    logger.warning(f"实例 {instance_id} 子进程已退出，退出码: {exit_code}")
                    await self._handle_crash(instance_id, instance, exit_code, restart_count, max_restarts)
                    restart_count = 0
                    continue

                if instance._heartbeat_task.done():
                    try:
                        exception = instance._heartbeat_task.exception()
                        if exception:
                            logger.error(f"实例 {instance_id} 心跳任务异常: {exception}")
                    except asyncio.InvalidStateError:
                        pass
                    except Exception as e:
                        logger.error(f"获取心跳任务异常失败: {e}")
                    logger.warning(f"实例 {instance_id} 心跳任务已退出，触发重启")
                    await self._handle_crash(instance_id, instance, -1, restart_count, max_restarts)
                    restart_count = 0
                    continue

                if instance._message_task.done():
                    try:
                        exception = instance._message_task.exception()
                        if exception:
                            logger.error(f"实例 {instance_id} 消息任务异常: {exception}")
                    except asyncio.InvalidStateError:
                        pass
                    except Exception as e:
                        logger.error(f"获取消息任务异常失败: {e}")
                    logger.info(f"重启消息任务")
                    instance._message_task = asyncio.create_task(self._message_loop(instance))

        except asyncio.CancelledError:
            logger.info(f"实例 {instance_id} 状态监控任务已取消")
        except Exception as e:
            logger.error(f"监控实例 {instance_id} 状态时出错: {e}", exc_info=True)
        finally:
            for task_name, task in [("心跳", instance._heartbeat_task), ("消息", instance._message_task)]:
                if task and not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=2.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"等待{task_name}任务取消超时")
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logger.warning(f"{task_name}任务取消时出错: {e}")

    async def _heartbeat_loop(self, instance: MaibotInstance) -> None:
        """心跳检测循环"""
        instance_id = instance.instance_id

        while instance.status == InstanceStatus.RUNNING:
            try:
                if instance.input_queue:
                    try:
                        instance.input_queue.put_nowait({"type": "ping"})
                    except Exception:
                        pass

                if instance.last_heartbeat:
                    elapsed = (datetime.now() - instance.last_heartbeat).total_seconds()
                    if elapsed > HEARTBEAT_TIMEOUT:
                        logger.warning(f"实例 {instance_id} 心跳超时 ({elapsed:.1f}s)，尝试重启...")
                        return

                await asyncio.sleep(5.0)

            except asyncio.CancelledError:
                logger.info(f"实例 {instance_id} 心跳循环已取消")
                break
            except Exception as e:
                logger.error(f"实例 {instance_id} 心跳循环出错: {e}", exc_info=True)
                await asyncio.sleep(5.0)

    async def _message_loop(self, instance: MaibotInstance) -> None:
        """消息处理循环"""
        instance_id = instance.instance_id

        while instance.status == InstanceStatus.RUNNING:
            try:
                if instance.output_queue:
                    if instance.output_queue.empty():
                        await asyncio.sleep(0.05)
                        continue

                    try:
                        msg = instance.output_queue.get_nowait()
                    except Exception:
                        await asyncio.sleep(0.05)
                        continue

                    msg_type = msg.get("type", "")
                    payload = msg.get("payload", {})

                    if msg_type == "pong":
                        instance.last_heartbeat = datetime.now()
                    elif msg_type == "status":
                        status = payload.get("status", "")
                        if status == "stopped":
                            logger.info(f"实例 {instance_id} 已停止")
                            instance.status = InstanceStatus.STOPPED
                            instance.started_at = None
                            self._cleanup_instance(instance)
                            return
                    elif msg_type == "log":
                        level = payload.get("level", "info")
                        msg_text = payload.get("message", "")
                        if level == "error":
                            print(f"[{instance_id}] {msg_text}")
                        elif level == "warning":
                            print(f"[{instance_id}] {msg_text}")
                        else:
                            print(f"[{instance_id}] {msg_text}")
                    elif msg_type == "signal":
                        signum = payload.get("signal", "")
                        logger.info(f"实例 {instance_id} 收到信号: {signum}")
                    elif msg_type == "message_reply":
                        unified_msg_origin = payload.get("unified_msg_origin", "")
                        segments = payload.get("segments", [])
                        processed_plain_text = payload.get("processed_plain_text", "")
                        logger.info(f"[{instance_id}] 📩 收到 message_reply")
                        asyncio.create_task(self._handle_instance_reply(instance_id, unified_msg_origin, segments, processed_plain_text))
                    elif msg_type == "kb_retrieve":
                        asyncio.create_task(self._handle_kb_retrieve(instance, payload))

                await asyncio.sleep(0.05)

            except asyncio.CancelledError:
                logger.info(f"实例 {instance_id} 消息循环已取消")
                break
            except Exception as e:
                logger.error(f"实例 {instance_id} 消息循环出错: {e}", exc_info=True)
                await asyncio.sleep(1.0)

    async def _handle_crash(self, instance_id: str, instance: MaibotInstance, exit_code: int, restart_count: int, max_restarts: int) -> None:
        """处理进程崩溃"""
        for task_name, task in [("心跳", instance._heartbeat_task), ("消息", instance._message_task)]:
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning(f"等待{task_name}任务取消超时")
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.warning(f"{task_name}任务取消时出错: {e}")

        if instance.lifecycle.get("restart_on_crash", True):
            if restart_count < max_restarts:
                delay = instance.lifecycle.get("restart_delay", 5000) / 1000
                logger.info(f"实例 {instance_id} 等待 {delay}s 后自动重启 ({restart_count + 1}/{max_restarts})")
                await asyncio.sleep(delay)
                self._cleanup_instance(instance)
                instance.status = InstanceStatus.RESTARTING
                await self.start_instance(instance_id)
            else:
                logger.error(f"实例 {instance_id} 崩溃重启次数超限 ({restart_count}/{max_restarts})")
                instance.status = InstanceStatus.ERROR
                instance.error_message = f"子进程异常退出，退出码: {exit_code}"
                instance.started_at = None
                self._cleanup_instance(instance)
        else:
            instance.status = InstanceStatus.ERROR
            instance.error_message = f"子进程异常退出，退出码: {exit_code}"
            instance.started_at = None
            self._cleanup_instance(instance)

    async def _handle_instance_reply(self, instance_id: str, unified_msg_origin: str, segments: List[dict], processed_plain_text: str) -> None:
        """处理子进程返回的回复消息"""
        try:
            from astrbot.core.maibot.maibot_adapter import get_astrbot_adapter
            from astrbot.core.maibot.maibot_adapter.send_handler import convert_maibot_to_astrbot

            logger.info(f"[{instance_id}] 📨 收到子进程回复")
            adapter = get_astrbot_adapter()
            event = adapter.get_event(unified_msg_origin)

            if not event:
                current_events = list(adapter._events.keys()) if hasattr(adapter, "_events") else []
                logger.error(f"[{instance_id}] ❌ 未找到事件: {unified_msg_origin[:16]}, 当前缓存: {current_events[:5]}...")
                return

            if not segments:
                logger.warning(f"[{instance_id}] ❌ 回复没有消息段")
                return

            message_chain = convert_maibot_to_astrbot(segments)
            await event.send(message_chain)
            logger.info(f"[{instance_id}] ✅ 回复已发送")

        except Exception as e:
            logger.error(f"[{instance_id}] ❌ 处理子进程回复失败: {e}", exc_info=True)

    async def _handle_kb_retrieve(self, instance: MaibotInstance, payload: Dict[str, Any]) -> None:
        """处理知识库检索请求"""
        request_id = payload.get("request_id", "")
        query = payload.get("query", "")
        kb_names = payload.get("kb_names", [])
        top_k_fusion = payload.get("top_k_fusion", 20)
        top_m_final = payload.get("top_m_final", 5)

        try:
            kb_manager = self._get_kb_manager()
            if kb_manager is None:
                logger.warning(f"[{instance.instance_id}] 知识库管理器未初始化")
                self._send_kb_result(instance, request_id, False, error="知识库管理器未初始化")
                return

            if not kb_names:
                self._send_kb_result(instance, request_id, True, results=[])
                return

            logger.info(f"[{instance.instance_id}] 知识库检索: {query[:50]}...")
            result = await kb_manager.retrieve(query=query, kb_names=kb_names, top_k_fusion=top_k_fusion, top_m_final=top_m_final)

            if result is None:
                self._send_kb_result(instance, request_id, True, results=[])
                return

            results = result.get("results", [])
            formatted_results = [
                {"content": r.get("content", ""), "score": r.get("score", 0.0), "kb_name": r.get("kb_name", ""), "doc_name": r.get("doc_name", "")}
                for r in results
            ]

            logger.info(f"[{instance.instance_id}] 知识库检索完成，返回 {len(formatted_results)} 条结果")
            self._send_kb_result(instance, request_id, True, results=formatted_results)

        except Exception as e:
            logger.error(f"[{instance.instance_id}] 知识库检索失败: {e}", exc_info=True)
            self._send_kb_result(instance, request_id, False, error=str(e))

    def _send_kb_result(self, instance: MaibotInstance, request_id: str, success: bool, results: List[Dict] = None, error: str = "") -> None:
        """发送知识库检索结果"""
        if instance.input_queue is None:
            logger.warning(f"[{instance.instance_id}] 无法发送知识库结果：队列未初始化")
            return

        try:
            instance.input_queue.put_nowait({
                "type": "kb_retrieve_result",
                "payload": {"request_id": request_id, "success": success, "results": results or [], "error": error}
            })
        except Exception as e:
            logger.error(f"[{instance.instance_id}] 发送知识库结果失败: {e}")

    def _get_kb_manager(self):
        """获取知识库管理器"""
        try:
            from astrbot.core.star.context import Context
            if hasattr(self, '_astrbot_context') and self._astrbot_context:
                return self._astrbot_context.kb_manager
            return None
        except Exception:
            return None

    def set_astrbot_context(self, context) -> None:
        """设置 AstrBot Context 引用"""
        self._astrbot_context = context
        logger.info("已设置 AstrBot Context 引用")

    async def restart_instance(self, instance_id: str) -> bool:
        """重启指定实例"""
        if instance_id not in self.instances:
            return False
        instance = self.instances[instance_id]
        logger.info(f"正在重启实例 {instance_id}...")
        stopped = await self.stop_instance(instance_id)
        if not stopped:
            logger.error(f"停止实例 {instance_id} 失败，无法重启")
            return False
        await asyncio.sleep(1.0)
        return await self.start_instance(instance_id)

    async def stop_instance(self, instance_id: str) -> bool:
        """停止指定实例"""
        if instance_id not in self.instances:
            return False
        instance = self.instances[instance_id]
        if instance.status == InstanceStatus.STOPPED:
            return True
        try:
            instance.status = InstanceStatus.STOPPING
            if instance._status_monitor_task:
                instance._status_monitor_task.cancel()
                instance._status_monitor_task = None
            if instance.input_queue:
                try:
                    instance.input_queue.put_nowait({"type": "stop"})
                    logger.info(f"已向实例 {instance_id} 发送停止命令")
                except Exception as e:
                    logger.warning(f"发送停止命令失败: {e}")
            if instance.process and instance.process.is_alive():
                instance.process.join(timeout=10)
                if instance.process.is_alive():
                    logger.warning(f"子进程未响应终止信号，强制终止...")
                    instance.process.terminate()
                    instance.process.join(timeout=5)
                    if instance.process.is_alive():
                        instance.process.kill()
            self._cleanup_instance(instance)
            instance.status = InstanceStatus.STOPPED
            instance.started_at = None
            logger.info(f"实例 {instance_id} 已停止")
            return True
        except Exception as e:
            instance.status = InstanceStatus.ERROR
            instance.error_message = str(e)
            logger.error(f"停止实例 {instance_id} 失败: {e}")
            return False

    def get_instance(self, instance_id: str) -> Optional[MaibotInstance]:
        return self.instances.get(instance_id)

    def get_all_instances(self) -> List[MaibotInstance]:
        return list(self.instances.values())

    def get_running_instances(self) -> List[MaibotInstance]:
        return [inst for inst in self.instances.values() if inst.status == InstanceStatus.RUNNING]

    def is_configured(self, instance_id: str) -> bool:
        if instance_id not in self.instances:
            return False
        instance = self.instances[instance_id]
        config_path = instance.get_config_path(self.data_root)
        return os.path.exists(config_path)

    async def send_message(self, instance_id: str, message_data: Dict[str, Any], unified_msg_origin: str, timeout: float = 30.0) -> Dict[str, Any]:
        """发送消息给指定实例（IPC 模式）"""
        if instance_id not in self.instances:
            raise ValueError(f"实例不存在: {instance_id}")
        instance = self.instances[instance_id]
        if instance.status != InstanceStatus.RUNNING:
            raise ValueError(f"实例 {instance_id} 未运行，当前状态: {instance.status.value}")
        if not instance.input_queue:
            raise ValueError(f"实例 {instance_id} 未初始化消息队列")

        cmd = {"type": "message", "payload": {"message_data": message_data, "unified_msg_origin": unified_msg_origin}}

        try:
            instance.input_queue.put_nowait(cmd)
            logger.debug(f"消息已发送到实例 {instance_id}")
        except Exception as e:
            logger.error(f"发送消息到实例 {instance_id} 失败: {e}")
            return {"success": False, "error": str(e)}

        start_time = time.time()
        while time.time() - start_time < timeout:
            import multiprocessing
            try:
                if instance.output_queue.empty():
                    await asyncio.sleep(0.05)
                    continue
                msg = instance.output_queue.get(timeout=1.0)
                msg_type = msg.get("type", "")
                if msg_type == "message_result":
                    payload = msg.get("payload", {})
                    success = payload.get("success", False)
                    result = payload.get("result")
                    error = payload.get("error", "")
                    logger.debug(f"实例 {instance_id} 消息处理结果: success={success}")
                    return {"success": success, "result": result, "error": error}
                else:
                    continue
            except multiprocessing.queues.Empty:
                continue
            except Exception as e:
                logger.error(f"获取消息处理结果时出错: {e}")
                return {"success": False, "error": str(e)}
        logger.warning(f"等待实例 {instance_id} 消息处理结果超时")
        return {"success": False, "error": "处理超时"}


_instance_manager: Optional[MaibotInstanceManager] = None


async def initialize_instance_manager(data_root: str = "data/maibot") -> MaibotInstanceManager:
    """初始化全局实例管理器"""
    global _instance_manager
    _instance_manager = MaibotInstanceManager(data_root)
    await _instance_manager.initialize()
    return _instance_manager


def get_instance_manager() -> Optional[MaibotInstanceManager]:
    """获取全局实例管理器"""
    return _instance_manager


async def start_maibot(instance_id: str) -> bool:
    """通过实例ID启动 MaiBot 实例"""
    manager = get_instance_manager()
    if manager is None:
        manager = await initialize_instance_manager()
    return await manager.start_instance(instance_id)


async def stop_maibot(instance_id: str) -> bool:
    """停止指定的 MaiBot 实例"""
    manager = get_instance_manager()
    if manager is None:
        return False
    return await manager.stop_instance(instance_id)


def list_instances() -> List[Dict[str, Any]]:
    """列出所有实例"""
    manager = get_instance_manager()
    if manager is None:
        return []
    return [inst.to_dict() for inst in manager.get_all_instances()]


def get_instance_status(instance_id: str) -> Optional[Dict[str, Any]]:
    """获取实例状态"""
    manager = get_instance_manager()
    if manager is None:
        return None
    instance = manager.get_instance(instance_id)
    if instance:
        return instance.to_dict()
    return None


async def send_message_to_instance(instance_id: str, message_data: Dict[str, Any], unified_msg_origin: str, timeout: float = 30.0) -> Dict[str, Any]:
    """便捷函数：发送消息给指定实例"""
    manager = get_instance_manager()
    if manager is None:
        return {"success": False, "error": "实例管理器未初始化"}
    return await manager.send_message(instance_id, message_data, unified_msg_origin, timeout)


__all__ = [
    "MaibotInstanceManager",
    "MaibotInstance",
    "InstanceStatus",
    "initialize_instance_manager",
    "get_instance_manager",
    "start_maibot",
    "stop_maibot",
    "list_instances",
    "get_instance_status",
    "send_message_to_instance",
]
