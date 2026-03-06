"""麦麦管理 API 路由

提供麦麦实例的创建、删除、启动、停止等管理功能。
"""

import os
from datetime import datetime

import tomlkit
from quart import request

from astrbot.api import logger
from astrbot.core.core_lifecycle import AstrBotCoreLifecycle
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .route import Response, Route, RouteContext


class MaiBotManagerRoute(Route):
    """麦麦管理 API 路由"""

    def __init__(self, context: RouteContext, core_lifecycle: AstrBotCoreLifecycle):
        super().__init__(context)
        self.core_lifecycle = core_lifecycle
        self.routes = {
            # ============ 实例管理 ============
            "/maibot/instances": [
                ("GET", self.get_instances),
                ("POST", self.create_instance),
            ],
            "/maibot/instances/default_config": [
                ("GET", self.get_maibot_default_config),
            ],
            "/maibot/instances/<instance_id>": [
                ("GET", self.get_instance),
                ("PUT", self.update_instance),
                ("DELETE", self.delete_instance),
            ],
            # ============ 生命周期管理 ============
            "/maibot/instances/<instance_id>/start": ("POST", self.start_instance),
            "/maibot/instances/<instance_id>/stop": ("POST", self.stop_instance),
            "/maibot/instances/<instance_id>/restart": ("POST", self.restart_instance),
            # ============ 实例配置管理 ============
            "/maibot/instances/<instance_id>/config": [
                ("GET", self.get_instance_config),
                ("PUT", self.save_instance_config),
            ],
            # ============ 实例日志管理 ============
            "/maibot/instances/<instance_id>/logs": [
                ("GET", self.get_instance_logs),
            ],
            "/maibot/instances/<instance_id>/logs/clear": ("POST", self.clear_instance_logs),
            "/maibot/instances/<instance_id>/logs/download": ("GET", self.download_instance_logs),
            # ============ 运行状态 ============
            "/maibot/running": ("GET", self.get_running_instances),
            "/maibot/default": [
                ("GET", self.get_default_instance),
                ("PUT", self.set_default_instance),
            ],
            # ============ 文本库 data.txt 管理 ============
            "/maibot/data": [
                ("GET", self.get_data_txt),
                ("PUT", self.save_data_txt),
            ],
            # ============ 路由规则管理 ============
            "/maibot/routing/rules": [
                ("GET", self.get_routing_rules),
                ("PUT", self.save_routing_rules),
                ("DELETE", self.clear_routing_rules),
            ],
        }
        self.register_routes()

    @property
    def maibot_manager(self):
        """获取 MaiBot 实例管理器"""
        return getattr(self.core_lifecycle, "maibot_manager", None)

    def _check_maibot_manager(self) -> bool:
        """检查 maibot_manager 是否可用"""
        if not self.maibot_manager:
            logger.warning("MaiBot 管理器未初始化")
            return False
        return True

    # ============ 实例管理 ============

    async def get_instances(self):
        """获取所有实例"""
        if not self._check_maibot_manager():
            return Response().error("麦麦管理器未初始化").__dict__, 500

        try:
            instances = self.maibot_manager.get_all_instances()
            return Response().ok({
                "instances": [inst.to_dict() for inst in instances],
                "total": len(instances),
            }).__dict__
        except Exception as e:
            logger.error(f"获取实例列表失败: {e}", exc_info=True)
            return Response().error(f"获取实例列表失败: {e}").__dict__, 500

    def _get_template_config_path(self) -> str:
        """获取默认模板配置文件路径"""
        # 模板文件路径: astrbot/core/maibot/template/bot_config_template.toml
        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "core", "maibot", "template"
        )
        return os.path.join(template_dir, "bot_config_template.toml")

    async def get_maibot_default_config(self):
        """获取默认模板配置"""
        try:
            config_path = self._get_template_config_path()

            if not os.path.exists(config_path):
                return Response().error("默认模板配置文件不存在").__dict__, 404

            # 读取 TOML 文件
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = tomlkit.load(f)

            # 清理配置：移除注释相关的字段
            self._clean_config(config_data)

            return Response().ok({
                "config": config_data,
            }).__dict__
        except Exception as e:
            logger.error(f"获取默认模板配置失败: {e}", exc_info=True)
            return Response().error(f"获取默认配置失败: {e}").__dict__, 500

    def _clean_config(self, config: dict):
        """清理配置数据，移除注释相关字段"""
        keys_to_remove = []
        for key in config:
            if key.startswith("_") or key.lower().endswith("_comment"):
                keys_to_remove.append(key)
            elif isinstance(config[key], dict):
                self._clean_config(config[key])
        for key in keys_to_remove:
            config.pop(key, None)

    async def get_instance(self, instance_id: str):
        """获取单个实例详情"""
        if not self._check_maibot_manager():
            return Response().error("麦麦管理器未初始化").__dict__, 500

        try:
            instance = self.maibot_manager.get_instance(instance_id)
            if not instance:
                return Response().error(f"实例 {instance_id} 不存在").__dict__, 404

            return Response().ok(instance.to_dict()).__dict__
        except Exception as e:
            logger.error(f"获取实例详情失败: {e}", exc_info=True)
            return Response().error(f"获取实例详情失败: {e}").__dict__, 500

    async def create_instance(self):
        """创建新实例

        Request Body:
            - instance_id: 实例 ID (必填)
            - name: 实例名称 (必填)
            - description: 描述
            - port: 服务端口
            - web_port: WebUI 端口
            - enable_webui: 是否启用 WebUI
            - enable_socket: 是否启用 Socket
            - config: TOML 配置内容（可选）
        """
        if not self._check_maibot_manager():
            return Response().error("麦麦管理器未初始化").__dict__, 500

        try:
            data = await request.get_json()

            instance_id = data.get("instance_id")
            name = data.get("name")
            if not instance_id or not name:
                return Response().error("实例 ID 和名称不能为空").__dict__, 400

            instance = await self.maibot_manager.create_instance(
                instance_id=instance_id,
                name=name,
                description=data.get("description", ""),
                host=data.get("host", "127.0.0.1"),
                port=data.get("port", 8000),
                web_host=data.get("web_host", "127.0.0.1"),
                web_port=data.get("web_port", 8001),
                enable_webui=data.get("enable_webui", False),
                enable_socket=data.get("enable_socket", False),
                config_updates=data.get("config_updates"),
            )

            return Response().ok({
                "id": instance.instance_id,
                "name": instance.name,
                "message": "实例创建成功",
            }).__dict__

        except ValueError as e:
            return Response().error(str(e)).__dict__, 409
        except Exception as e:
            logger.error(f"创建实例失败: {e}", exc_info=True)
            return Response().error(f"创建实例失败: {e}").__dict__, 500

    async def update_instance(self, instance_id: str):
        """更新实例配置

        Request Body:
            - name: 实例名称
            - description: 描述
            - lifecycle: 生命周期配置 {"restart_on_crash": bool, "max_restarts": int, "restart_delay": int}
            - host: 服务主机地址
            - port: 服务端口
            - web_host: WebUI 主机地址
            - web_port: WebUI 端口
            - enable_webui: 是否启用 WebUI
            - enable_socket: 是否启用 Socket
            - logging: 日志配置 {"enable_console": bool, "log_level": str}
            - knowledge_base: 知识库配置 {"enabled": bool, "kb_names": [], "fusion_top_k": int, "return_top_k": int}
        """
        if not self._check_maibot_manager():
            return Response().error("麦麦管理器未初始化").__dict__, 500

        try:
            instance = self.maibot_manager.get_instance(instance_id)
            if not instance:
                return Response().error(f"实例 {instance_id} 不存在").__dict__, 404

            data = await request.get_json()

            # 更新基本字段
            if "name" in data:
                instance.name = data["name"]
            if "description" in data:
                instance.description = data["description"]
            if "lifecycle" in data:
                instance.lifecycle.update(data["lifecycle"])

            # 更新网络配置字段
            if "host" in data:
                instance.host = data["host"]
            if "port" in data:
                instance.port = data["port"]
            if "web_host" in data:
                instance.web_host = data["web_host"]
            if "web_port" in data:
                instance.web_port = data["web_port"]
            if "enable_webui" in data:
                instance.enable_webui = data["enable_webui"]
            if "enable_socket" in data:
                instance.enable_socket = data["enable_socket"]

            # 更新日志配置
            if "logging" in data:
                instance.logging.update(data["logging"])

            # 更新知识库配置
            if "knowledge_base" in data:
                instance.knowledge_base.update(data["knowledge_base"])

            # 保存元数据到 instances_meta.json
            instance.updated_at = None  # 会在保存时自动设置
            await self.maibot_manager._save_instances_metadata()

            # 如果修改了 webui 相关的网络配置，同步更新 TOML 文件
            sync_toml_fields = ["enable_webui", "enable_socket", "logging", "knowledge_base"]
            should_sync_toml = any(field in data for field in sync_toml_fields)

            if should_sync_toml:
                await self._sync_instance_config_to_toml(instance_id, instance)

            return Response().ok({
                "id": instance_id,
                "message": "配置已更新",
            }).__dict__

        except Exception as e:
            logger.error(f"更新实例配置失败: {e}", exc_info=True)
            return Response().error(f"更新实例配置失败: {e}").__dict__, 500

    async def _sync_instance_config_to_toml(self, instance_id: str, instance):
        """同步实例配置到 TOML 文件

        将 instances_meta.json 中的配置同步到 TOML 配置文件
        """
        try:
            config_path = self._get_instance_config_path(instance_id)
            if not os.path.exists(config_path):
                logger.warning(f"实例 {instance_id} 的 TOML 配置文件不存在，跳过同步")
                return

            # 读取 TOML 配置
            with open(config_path, "r", encoding="utf-8") as f:
                doc = tomlkit.load(f)

            # 同步 webui 配置
            if "webui" not in doc:
                doc["webui"] = {}
            doc["webui"]["enabled"] = instance.enable_webui

            # 同步日志配置
            if "log" not in doc:
                doc["log"] = {}
            if hasattr(instance, "logging") and instance.logging:
                if "log_level" in instance.logging:
                    doc["log"]["log_level"] = instance.logging.get("log_level", "INFO")
                if "console_log_level" in instance.logging:
                    doc["log"]["console_log_level"] = instance.logging.get("console_log_level", "INFO")

            # 同步知识库配置 (lpmm_knowledge)
            if "lpmm_knowledge" not in doc:
                doc["lpmm_knowledge"] = {}
            if hasattr(instance, "knowledge_base") and instance.knowledge_base:
                kb_config = instance.knowledge_base
                doc["lpmm_knowledge"]["enable"] = kb_config.get("enabled", False)

            # 保存 TOML 配置
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(tomlkit.dumps(doc))

            logger.info(f"已同步实例 {instance_id} 的配置到 TOML 文件")

        except Exception as e:
            logger.error(f"同步实例 {instance_id} 配置到 TOML 失败: {e}", exc_info=True)

    async def delete_instance(self, instance_id: str):
        """删除实例

        Query Parameters:
            - delete_data: 是否删除数据目录 (默认 false)
        """
        if not self._check_maibot_manager():
            return Response().error("麦麦管理器未初始化").__dict__, 500

        try:
            # 检查实例是否存在
            instance = self.maibot_manager.get_instance(instance_id)
            if not instance:
                return Response().error(f"实例 {instance_id} 不存在").__dict__, 404

            # 如果实例正在运行，先停止
            if instance.status.value == "running":
                await self.maibot_manager.stop_instance(instance_id)

            # 从管理器中移除
            del self.maibot_manager.instances[instance_id]
            await self.maibot_manager._save_instances_metadata()

            return Response().ok({
                "deleted": True,
                "instance_id": instance_id,
            }).__dict__

        except Exception as e:
            logger.error(f"删除实例失败: {e}", exc_info=True)
            return Response().error(f"删除实例失败: {e}").__dict__, 500

    # ============ 生命周期管理 ============

    async def start_instance(self, instance_id: str):
        """启动实例"""
        if not self._check_maibot_manager():
            return Response().error("麦麦管理器未初始化").__dict__, 500

        try:
            success = await self.maibot_manager.start_instance(instance_id)
            if not success:
                instance = self.maibot_manager.get_instance(instance_id)
                error_msg = instance.error_message if instance else "启动失败"
                return Response().error(error_msg).__dict__, 400

            return Response().ok({
                "id": instance_id,
                "status": "starting",
                "message": "实例启动中...",
            }).__dict__

        except Exception as e:
            logger.error(f"启动实例失败: {e}", exc_info=True)
            return Response().error(f"启动实例失败: {e}").__dict__, 500

    async def stop_instance(self, instance_id: str):
        """停止实例"""
        if not self._check_maibot_manager():
            return Response().error("麦麦管理器未初始化").__dict__, 500

        try:
            success = await self.maibot_manager.stop_instance(instance_id)
            if not success:
                return Response().error("停止失败").__dict__, 400

            return Response().ok({
                "id": instance_id,
                "status": "stopping",
                "message": "实例停止中...",
            }).__dict__

        except Exception as e:
            logger.error(f"停止实例失败: {e}", exc_info=True)
            return Response().error(f"停止实例失败: {e}").__dict__, 500

    async def restart_instance(self, instance_id: str):
        """重启实例"""
        if not self._check_maibot_manager():
            return Response().error("麦麦管理器未初始化").__dict__, 500

        try:
            success = await self.maibot_manager.restart_instance(instance_id)
            if not success:
                return Response().error("重启失败").__dict__, 400

            return Response().ok({
                "id": instance_id,
                "status": "restarting",
                "message": "实例重启中...",
            }).__dict__

        except Exception as e:
            logger.error(f"重启实例失败: {e}", exc_info=True)
            return Response().error(f"重启实例失败: {e}").__dict__, 500

    # ============ 运行状态 ============

    async def get_running_instances(self):
        """获取运行中的实例"""
        if not self._check_maibot_manager():
            return Response().error("麦麦管理器未初始化").__dict__, 500

        try:
            running = self.maibot_manager.get_running_instances()
            return Response().ok({
                "instances": [inst.to_dict() for inst in running],
                "total": len(running),
            }).__dict__
        except Exception as e:
            logger.error(f"获取运行中实例失败: {e}", exc_info=True)
            return Response().error(f"获取运行中实例失败: {e}").__dict__, 500

    async def get_default_instance(self):
        """获取默认实例"""
        if not self._check_maibot_manager():
            return Response().error("麦麦管理器未初始化").__dict__, 500

        try:
            default = None
            for instance in self.maibot_manager.instances.values():
                if instance.is_default:
                    default = instance
                    break
            if not default:
                # 如果没有标记为默认的，返回第一个
                instances = list(self.maibot_manager.instances.values())
                if instances:
                    default = instances[0]

            if default:
                return Response().ok(default.to_dict()).__dict__
            return Response().error("未设置默认实例").__dict__, 404
        except Exception as e:
            logger.error(f"获取默认实例失败: {e}", exc_info=True)
            return Response().error(f"获取默认实例失败: {e}").__dict__, 500

    async def set_default_instance(self):
        """设置默认实例

        Request Body:
            - instance_id: 实例 ID
        """
        if not self._check_maibot_manager():
            return Response().error("麦麦管理器未初始化").__dict__, 500

        try:
            data = await request.get_json()
            instance_id = data.get("instance_id")
            if not instance_id:
                return Response().error("实例 ID 不能为空").__dict__, 400

            instance = self.maibot_manager.get_instance(instance_id)
            if not instance:
                return Response().error(f"实例 {instance_id} 不存在").__dict__, 404

            # 取消之前的默认实例
            for inst in self.maibot_manager.instances.values():
                inst.is_default = False

            # 设置新的默认实例
            instance.is_default = True
            await self.maibot_manager._save_instances_metadata()

            return Response().ok({
                "instance_id": instance_id,
                "message": "默认实例已更新",
            }).__dict__
        except Exception as e:
            logger.error(f"设置默认实例失败: {e}", exc_info=True)
            return Response().error(f"设置默认实例失败: {e}").__dict__, 500

    # ============ 路由规则管理 ============

    async def get_routing_rules(self):
        """获取路由规则"""
        try:
            adapter = self.maibot_adapter
            if not adapter:
                return Response().error("适配器未初始化").__dict__, 500

            return Response().ok({
                "default_instance": adapter.message_router.default_instance,
                "rules": adapter.message_router.get_rules(),
            }).__dict__
        except Exception as e:
            logger.error(f"获取路由规则失败: {e}", exc_info=True)
            return Response().error(f"获取路由规则失败: {e}").__dict__, 500

    async def save_routing_rules(self):
        """保存路由规则

        Request Body:
            - default_instance: 默认实例 ID
            - rules: 路由规则列表 [{"chat_id": "...", "instance_id": "..."}]
        """
        try:
            adapter = self.maibot_adapter
            if not adapter:
                return Response().error("适配器未初始化").__dict__, 500

            data = await request.get_json()

            if "default_instance" in data:
                adapter.message_router.set_default_instance(data["default_instance"])

            if "rules" in data:
                # 清空现有规则并添加新规则
                adapter.message_router.clear_rules()
                for rule in data["rules"]:
                    chat_id = rule.get("chat_id")
                    instance_id = rule.get("instance_id")
                    if chat_id and instance_id:
                        adapter.message_router.add_rule(chat_id, instance_id)

            await adapter.message_router.save_config()

            return Response().ok({"message": "路由规则已保存"}).__dict__
        except Exception as e:
            logger.error(f"保存路由规则失败: {e}", exc_info=True)
            return Response().error(f"保存路由规则失败: {e}").__dict__, 500

    async def clear_routing_rules(self):
        """清空路由规则"""
        try:
            adapter = self.maibot_adapter
            if not adapter:
                return Response().error("适配器未初始化").__dict__, 500

            adapter.message_router.clear_rules()
            await adapter.message_router.save_config()

            return Response().ok({"message": "路由规则已清空"}).__dict__
        except Exception as e:
            logger.error(f"清空路由规则失败: {e}", exc_info=True)
            return Response().error(f"清空路由规则失败: {e}").__dict__, 500

    # ============ 实例配置管理 ============

    def _get_instance_config_path(self, instance_id: str) -> str:
        """获取实例配置文件路径"""
        # 从 astrbot_path 获取数据目录
        data_dir = get_astrbot_data_path()
        instances_dir = os.path.join(data_dir, "maibot", "config", "instances")
        return os.path.join(instances_dir, f"{instance_id}.toml")

    async def get_instance_config(self, instance_id: str):
        """获取实例配置文件内容

        Args:
            instance_id: 实例 ID
        """
        try:
            config_path = self._get_instance_config_path(instance_id)

            if not os.path.exists(config_path):
                return Response().error(f"实例 {instance_id} 的配置文件不存在").__dict__, 404

            # 读取 TOML 文件
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = tomlkit.load(f)

            return Response().ok({
                "instance_id": instance_id,
                "config": config_data,
            }).__dict__
        except Exception as e:
            logger.error(f"获取实例 {instance_id} 配置失败: {e}", exc_info=True)
            return Response().error(f"获取配置失败: {e}").__dict__, 500

    async def save_instance_config(self, instance_id: str):
        """保存实例配置文件（部分更新）

        Args:
            instance_id: 实例 ID

        Request Body:
            - raw_content: 原始 TOML 内容（只包含需要修改的 section）
        """
        try:
            config_path = self._get_instance_config_path(instance_id)

            if not os.path.exists(config_path):
                return Response().error(f"实例 {instance_id} 的配置文件不存在").__dict__, 404

            data = await request.get_json()
            raw_content = data.get("raw_content")

            if raw_content is not None:
                # 验证 TOML 格式
                try:
                    new_config = tomlkit.loads(raw_content)
                except Exception as e:
                    return Response().error(f"TOML 格式错误: {e}").__dict__, 400

                # 读取原配置
                with open(config_path, "r", encoding="utf-8") as f:
                    doc = tomlkit.load(f)

                # 只更新前端传来的 section（对每个 section 深度合并）
                for key, value in new_config.items():
                    if key == "inner":
                        # 保留 inner 版本号
                        if "version" in value:
                            doc.setdefault("inner", {})["version"] = value["version"]
                        continue

                    if key in doc:
                        # 已存在的 section 做深度合并
                        MaiBotManagerRoute._deep_merge(doc[key], value)
                    else:
                        # 新增的 section 直接添加
                        doc[key] = value

                # 格式化并保存
                with open(config_path, "w", encoding="utf-8") as f:
                    f.write(tomlkit.dumps(doc))
            else:
                return Response().error("请求数据中缺少 raw_content 字段").__dict__, 400

            logger.info(f"实例 {instance_id} 配置已保存")
            return Response().ok({
                "instance_id": instance_id,
                "message": "配置已保存",
            }).__dict__
        except Exception as e:
            logger.error(f"保存实例 {instance_id} 配置失败: {e}", exc_info=True)
            return Response().error(f"保存配置失败: {e}").__dict__, 500

    @staticmethod
    def _deep_merge(target: dict, source: dict):
        """递归深度合并字典，用于合并配置节

        Args:
            target: 目标字典（原配置）
            source: 源字典（新配置）
        """
        for key, value in source.items():
            if key in target:
                target_value = target[key]
                if isinstance(target_value, dict) and isinstance(value, dict):
                    # 两个都是字典，递归合并
                    MaiBotManagerRoute._deep_merge(target_value, value)
                elif isinstance(target_value, tomlkit.items.Table) and isinstance(value, dict):
                    # target 是 Table，source 是 dict，转为普通 dict 递归
                    MaiBotManagerRoute._deep_merge(dict(target_value), value)
                else:
                    # 直接覆盖（基础类型或类型不匹配）
                    target[key] = value
            else:
                # source 中的新字段直接添加
                target[key] = value

    # ============ 实例日志管理 ============

    def _get_instance_log_dir(self, instance_id: str) -> str:
        """获取实例日志目录路径"""
        # 日志目录: D:\work\Bot\logs\mailog\{instance_id}
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "logs", "mailog"))
        return os.path.join(base_dir, instance_id)

    async def get_instance_logs(self, instance_id: str):
        """获取实例日志

        Query Parameters:
            - limit: 返回行数限制 (默认 200)
            - offset: 跳过行数 (默认 0)
        """
        try:
            log_dir = self._get_instance_log_dir(instance_id)

            if not os.path.exists(log_dir):
                return Response().ok({
                    "logs": [],
                    "total": 0,
                    "message": f"实例 {instance_id} 的日志目录不存在",
                }).__dict__

            # 获取日志文件列表，按文件名排序（最新的在最后）
            log_files = sorted(
                [f for f in os.listdir(log_dir) if f.endswith(".log.jsonl")],
                reverse=True,  # 最新的文件优先
            )

            if not log_files:
                return Response().ok({
                    "logs": [],
                    "total": 0,
                }).__dict__

            # 解析查询参数
            limit = request.args.get("limit", default=200, type=int)
            offset = request.args.get("offset", default=0, type=int)

            all_logs = []
            total_lines = 0

            # 从最新的文件开始读取
            for log_file in log_files:
                file_path = os.path.join(log_dir, log_file)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue

                            # 解析 JSON 日志行，转换为易读的格式
                            try:
                                import json
                                log_data = json.loads(line)
                                formatted_log = self._format_log_line(log_data)
                                all_logs.append(formatted_log)
                                total_lines += 1
                            except json.JSONDecodeError:
                                # 如果不是 JSON，直接使用原始行
                                all_logs.append(line)
                                total_lines += 1

                            # 如果已经收集够足够的行，提前结束
                            if total_lines >= limit * 2:  # 多读一些以确保有足够数据
                                break
                except Exception as e:
                    logger.warning(f"读取日志文件 {log_file} 失败: {e}")
                    continue

                if total_lines >= limit * 2:
                    break

            # 应用分页
            paginated_logs = all_logs[offset : offset + limit]

            return Response().ok({
                "logs": paginated_logs,
                "total": total_lines,
            }).__dict__

        except Exception as e:
            logger.error(f"获取实例 {instance_id} 日志失败: {e}", exc_info=True)
            return Response().error(f"获取日志失败: {e}").__dict__, 500

    def _format_log_line(self, log_data: dict) -> str:
        """格式化单条日志为可读字符串"""
        try:
            # 提取时间戳
            timestamp = log_data.get("timestamp", "")
            # 提取日志级别
            level = log_data.get("level", "INFO")
            # 提取事件/消息
            event = log_data.get("event", "")
            # 提取日志器名称
            logger_name = log_data.get("logger_name", "")

            # 构建格式化的日志行
            formatted = f"[{timestamp}] [{level}] [{logger_name}] {event}"

            # 如果有额外字段，添加到末尾
            extra_fields = {}
            for key in ["logger_name", "event", "level", "timestamp"]:
                if key in log_data:
                    extra_fields[key] = log_data[key]

            # 添加其他有用信息
            if "pathname" in log_data:
                formatted += f" ({log_data['pathname']}:{log_data.get('lineno', '')})"

            return formatted
        except Exception:
            return str(log_data)

    async def clear_instance_logs(self, instance_id: str):
        """清空实例日志"""
        try:
            log_dir = self._get_instance_log_dir(instance_id)

            if not os.path.exists(log_dir):
                return Response().error(f"实例 {instance_id} 的日志目录不存在").__dict__, 404

            # 获取所有日志文件
            log_files = [f for f in os.listdir(log_dir) if f.endswith(".log.jsonl")]

            if not log_files:
                return Response().ok({"message": "没有日志文件需要清空"}).__dict__

            # 删除日志文件
            deleted_count = 0
            for log_file in log_files:
                file_path = os.path.join(log_dir, log_file)
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"删除日志文件 {log_file} 失败: {e}")

            return Response().ok({
                "message": f"已清空 {deleted_count} 个日志文件",
                "deleted_count": deleted_count,
            }).__dict__

        except Exception as e:
            logger.error(f"清空实例 {instance_id} 日志失败: {e}", exc_info=True)
            return Response().error(f"清空日志失败: {e}").__dict__, 500

    async def download_instance_logs(self, instance_id: str):
        """下载实例日志"""
        try:
            log_dir = self._get_instance_log_dir(instance_id)

            if not os.path.exists(log_dir):
                return Response().error(f"实例 {instance_id} 的日志目录不存在").__dict__, 404

            # 获取所有日志文件，按文件名排序
            log_files = sorted(
                [f for f in os.listdir(log_dir) if f.endswith(".log.jsonl")],
                reverse=True,
            )

            if not log_files:
                return Response().error("没有日志文件").__dict__, 404

            # 构建日志内容
            log_content = f"# 实例 {instance_id} 日志\n"
            log_content += f"# 生成时间: {datetime.now().isoformat()}\n"
            log_content += "#" + "=" * 50 + "\n\n"

            for log_file in log_files:
                file_path = os.path.join(log_dir, log_file)
                log_content += f"\n# ===== {log_file} =====\n"
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        log_content += f.read()
                except Exception as e:
                    log_content += f"# 读取文件失败: {e}\n"

            # 返回文件内容
            from quart import make_response
            response = await make_response(log_content)
            response.headers["Content-Type"] = "text/plain; charset=utf-8"
            response.headers["Content-Disposition"] = f'attachment; filename="{instance_id}_logs.txt"'
            return response

        except Exception as e:
            logger.error(f"下载实例 {instance_id} 日志失败: {e}", exc_info=True)
            return Response().error(f"下载日志失败: {e}").__dict__, 500

    # ============ 文本库 data.txt 管理 ============

    def _get_data_txt_path(self) -> str:
        """获取共用的 data.txt 文件路径"""
        # 共用 data.txt: D:\work\Bot\data\maibot\data.txt
        # 使用 astrbot_data_path 获取正确路径
        data_dir = get_astrbot_data_path()
        return os.path.join(data_dir, "maibot", "data.txt")

    async def get_data_txt(self):
        """获取 data.txt 内容"""
        try:
            data_txt_path = self._get_data_txt_path()

            if not os.path.exists(data_txt_path):
                # 文件不存在，返回空内容
                return Response().ok({
                    "content": "",
                    "exists": False,
                }).__dict__

            with open(data_txt_path, "r", encoding="utf-8") as f:
                content = f.read()

            return Response().ok({
                "content": content,
                "exists": True,
            }).__dict__

        except Exception as e:
            logger.error(f"获取实例 {instance_id} 的 data.txt 失败: {e}", exc_info=True)
            return Response().error(f"获取文件失败: {e}").__dict__, 500

    async def save_data_txt(self):
        """保存 data.txt 内容"""
        try:
            data_txt_path = self._get_data_txt_path()

            # 确保目录存在
            os.makedirs(os.path.dirname(data_txt_path), exist_ok=True)

            data = await request.get_json()
            content = data.get("content", "")

            with open(data_txt_path, "w", encoding="utf-8") as f:
                f.write(content)

            return Response().ok({
                "message": "文本库已保存",
            }).__dict__

        except Exception as e:
            logger.error(f"保存 data.txt 失败: {e}", exc_info=True)
            return Response().error(f"保存文件失败: {e}").__dict__, 500

    @property
    def maibot_adapter(self):
        """获取 MaiBot 适配器"""
        from astrbot.core.maibot.maibot_adapter import get_astrbot_adapter
        return get_astrbot_adapter()
