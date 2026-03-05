"""
子进程入口模块

作为子进程的主入口点，负责：
1. 从 input_queue 读取控制命令和消息
2. 执行 MaiBotCore 的初始化和启动
3. 通过 output_queue 发送状态更新、日志和回复
"""

import asyncio
import multiprocessing
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# 确保项目根目录在路径中
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 计算 MaiBot 项目路径并设置为环境变量（必须在导入 MaiBot 之前设置）
MAIBOT_PATH = os.path.join(PROJECT_ROOT, "MaiBot")
os.environ["MAIBOT_PATH"] = MAIBOT_PATH

# 默认日志配置
DEFAULT_LOG_CONFIG = {
    "enable_console": True,
    "log_level": "INFO",
}


def _run_subprocess_main(
    instance_id: str,
    data_root: str,
    config: Dict[str, Any],
    input_queue: multiprocessing.Queue,
    output_queue: multiprocessing.Queue,
):
    """同步包装函数，用于 multiprocessing.Process

    创建一个新的事件循环并运行异步的 subprocess_main_async
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            subprocess_main_async(
                instance_id=instance_id,
                data_root=data_root,
                config=config,
                input_queue=input_queue,
                output_queue=output_queue,
            )
        )
    finally:
        loop.close()


async def subprocess_main_async(
    instance_id: str,
    data_root: str,
    config: Dict[str, Any],
    input_queue: multiprocessing.Queue,
    output_queue: multiprocessing.Queue,
):
    """
    子进程主入口函数（异步版本）

    Args:
        instance_id: 实例ID
        data_root: 数据根目录
        config: 实例配置字典
        input_queue: 命令输入队列（主进程 -> 子进程）
        output_queue: 状态输出队列（子进程 -> 主进程）
    """
    import signal

    # 1. 先初始化实例日志系统（在导入任何 MaiBot 模块之前）
    from astrbot.core.maibot.maibot_adapter.subprocess.logger import (
        _mark_subprocess_mode,
        initialize_maibot_logger,
        get_logger,
        set_log_publisher,
    )

    # 立即标记子进程模式
    _mark_subprocess_mode()

    log_config = config.get("logging", DEFAULT_LOG_CONFIG)
    enable_console = log_config.get("enable_console", True)

    # 2. 初始化 IPC 服务端
    from astrbot.core.maibot.maibot_adapter.ipc import LocalServer

    ipc_server = LocalServer(
        input_queue=input_queue,
        output_queue=output_queue,
        instance_id=instance_id,
    )

    # 设置日志发布回调
    def send_log_to_main(level: str, msg: str):
        ipc_server.send_log(level, msg)

    if enable_console:
        set_log_publisher(send_log_to_main)

    initialize_maibot_logger(
        instance_id=instance_id,
        log_level=log_config.get("log_level", "INFO"),
        enable_console=enable_console,
    )
    maibot_logger = get_logger("subprocess")

    # 3. 导入 MaiBot
    from astrbot.core.maibot.src import MaiBotCore

    # 获取实例日志目录路径
    base_log_dir = Path(config.get("data_root", data_root)).parent / "logs" / "mailog"

    # 设置子进程信号处理
    def signal_handler(signum, frame):
        ipc_server.send_status("signal", f"收到信号: {signum}")

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    maibot_core: Optional[MaiBotCore] = None
    running = True
    shutdown_requested = False

    # 辅助函数：发送日志
    def send_log(level: str, msg: str, exc_info: bool = False):
        ipc_server.send_log(level, msg)

    ipc_server.send_status("starting", "子进程启动中...")

    # 打印路径信息用于调试
    maibot_logger.info(f"PROJECT_ROOT: {PROJECT_ROOT}")
    maibot_logger.info(f"MAIBOT_PATH: {MAIBOT_PATH}")
    maibot_logger.info(f"MAIBOT_PATH exists: {os.path.exists(MAIBOT_PATH)}")
    maibot_logger.info(f"WebUI dist exists: {os.path.exists(os.path.join(MAIBOT_PATH, 'webui', 'dist'))}")

    try:
        send_log("info", f"子进程启动: instance_id={instance_id}, data_root={data_root}")
        send_log("info", f"MAIBOT_PATH: {MAIBOT_PATH}")

        # 清除缓存的 API 实例
        # from astrbot.core.maibot.src.common.message.api import clear_cached_api
        # clear_cached_api()

        # 创建 MaiBotCore 实例
        maibot_core = MaiBotCore(instance_id=instance_id, config=config)

        # 初始化 MaiBot
        ipc_server.send_status("initializing", "正在初始化 MaiBot...")
        send_log("info", "开始初始化 MaiBotCore")

        try:
            await maibot_core.initialize()
            send_log("info", "MaiBotCore 初始化完成")
            ipc_server.send_status("initialized", "初始化完成，启动中...")

            # 启动 MaiBot
            await maibot_core.start()
            send_log("info", "MaiBotCore 启动完成")
            ipc_server.send_status("running", "运行中")

        except SystemExit as e:
            if e.code == 0:
                ipc_server.send_status("config_needed", "配置已创建，请填写后重新启动")
                send_log("warning", "配置文件不存在，已创建模板")
                return
            else:
                ipc_server.send_status("error", f"初始化退出: {e.code}")
                send_log("error", f"初始化退出，退出码: {e.code}")
                return
        except Exception as e:
            ipc_server.send_status("error", f"初始化失败: {e}")
            send_log("error", f"初始化失败: {e}")
            import traceback
            send_log("error", traceback.format_exc())
            return

        # 4. 初始化回复处理器，注册到 maim_message API
        from astrbot.core.maibot.maibot_adapter.send_handler import create_reply_handler
        from astrbot.core.maibot.src.common.message.api import get_global_api

        reply_handler = create_reply_handler(ipc_server)
        reply_handler.set_logger(send_log)

        # 获取 maim_message 的全局 API，注册发送消息处理器
        send_log("info", "[子进程] 准备注册回复处理器到 maim_message API...")
        global_api = get_global_api()
        global_api.register_send_message_handler(reply_handler.handle_outgoing_message)
        send_log("info", "[子进程] 回复处理器已注册到 maim_message API（register_send_message_handler）")

        # 5. 设置知识库适配器
        from astrbot.core.maibot.src.chat.knowledge.knowledge_base_adapter import (
            KnowledgeBaseAdapter,
            create_kb_adapter,
            cache_kb_response,
        )
        KnowledgeBaseAdapter.set_ipc_queues(output_queue, instance_id)

        # 注册知识库结果处理器
        ipc_server.register_kb_result_handler(cache_kb_response)

        # 从配置中读取知识库设置
        kb_config = config.get("knowledge_base", {})
        if kb_config.get("enabled", False):
            kb_names = kb_config.get("kb_names", [])
            fusion_top_k = kb_config.get("fusion_top_k", 5)
            return_top_k = kb_config.get("return_top_k", 20)

            # 设置知识库配置到 kb_query_manager（用于长思考模式等）
            from astrbot.core.maibot.src.chat.knowledge.planner.kb_query_manager import set_kb_config
            set_kb_config(kb_config)
            send_log("info", f"知识库配置已设置: long_thinking_enabled={kb_config.get('long_thinking_enabled', False)}")

            # 即使 kb_names 为空也创建适配器，让适配器自动获取所有知识库
            adapter = create_kb_adapter(
                kb_names=kb_names,  # 传空列表，由适配器自行获取所有知识库
                fusion_top_k=fusion_top_k,
                return_top_k=return_top_k,
            )
            send_log("info", f"知识库适配器已创建: kb_names={kb_names if kb_names else '(自动获取所有)'}")

        # 6. 消息处理函数
        async def _handle_message(message_data: Dict[str, Any], unified_msg_origin: str) -> None:
            """处理来自主进程的消息"""
            try:
                if not message_data:
                    ipc_server.send_message_result(False, error="消息数据为空")
                    return

                send_log("info", f"收到消息: unified_msg_origin={unified_msg_origin[:16] if unified_msg_origin else 'unknown'}...")

                # 获取 MaiBot 的 ChatBot 实例处理消息
                from astrbot.core.maibot.src.chat.message_receive.bot import chat_bot

                send_log("info", "调用 chat_bot.message_process...")
                await chat_bot.message_process(message_data)
                send_log("info", "chat_bot.message_process 完成")

                ipc_server.send_message_result(True, result={"status": "processed"})

            except Exception as e:
                send_log("error", f"处理消息失败: {e}")
                ipc_server.send_message_result(False, error=str(e))

        # 注册消息处理器
        ipc_server.register_message_handler(_handle_message)

        # 7. 主循环：处理来自主进程的命令
        send_log("info", "开始处理命令...")
        while running:
            try:
                # 轮询输入队列
                msg = await ipc_server.poll_input(timeout=0.05)
                if msg is None:
                    continue

                # 处理消息
                result = await ipc_server.process_input(msg)
                if result == "stop":
                    send_log("info", "收到停止命令")
                    running = False
                    shutdown_requested = True
                    break

            except Exception as e:
                send_log("error", f"处理命令时出错: {e}")
                continue

    except Exception as e:
        ipc_server.send_status("error", f"子进程异常: {e}")
        send_log("error", f"子进程异常: {e}")
        import traceback
        send_log("error", traceback.format_exc())
        running = False

    finally:
        # 关闭 MaiBot
        if maibot_core and shutdown_requested:
            try:
                await maibot_core.shutdown()
                send_log("info", "MaiBot 已关闭")
            except Exception as e:
                send_log("error", f"关闭 MaiBot 时出错: {e}")

        ipc_server.send_status("stopped", "子进程已停止")
        send_log("info", "子进程退出")


# 保持向后兼容
def subprocess_main(
    instance_id: str,
    data_root: str,
    config: Dict[str, Any],
    input_queue: multiprocessing.Queue,
    output_queue: multiprocessing.Queue,
):
    """子进程主入口函数（保持同步以兼容 multiprocessing）"""
    _run_subprocess_main(instance_id, data_root, config, input_queue, output_queue)


if __name__ == "__main__":
    """
    Windows 下 multiprocessing 需要 __main__ 保护
    直接运行时可接收参数进行测试
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(description="MaiBot 子进程入口")
    parser.add_argument("--instance-id", required=True, help="实例ID")
    parser.add_argument("--data-root", required=True, help="数据根目录")
    parser.add_argument("--config", required=True, help="配置JSON字符串")

    args = parser.parse_args()

    # 创建测试用的队列
    input_queue = multiprocessing.Queue()
    output_queue = multiprocessing.Queue()

    config = json.loads(args.config)

    print(f"启动子进程: instance_id={args.instance_id}")
    print(f"数据目录: {args.data_root}")
    print(f"配置: {config}")

    # 启动子进程
    p = multiprocessing.Process(
        target=subprocess_main,
        args=(args.instance_id, args.data_root, config, input_queue, output_queue),
    )
    p.start()

    # 等待子进程完成
    p.join()

    print(f"子进程已退出，退出码: {p.exitcode}")
