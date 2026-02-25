"""
MaiBot 多实例真实测试

测试真实的生命周期管理：启动、重启、关闭
"""

import asyncio
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from astrbot.core.maibot.maibot_adapter import (
    initialize_instance_manager,
    InstanceStatus,
)


async def test_real_lifecycle():
    """真实测试麦麦生命周期"""
    print("=" * 60)
    print("MaiBot 多实例生命周期真实测试")
    print("=" * 60)

    # 测试数据目录
    data_root = "test/data/maibot"
    print(f"\n使用数据目录: {data_root}")

    # 1. 初始化实例管理器
    print("\n[1] 初始化实例管理器...")
    manager = await initialize_instance_manager(data_root)
    print(f"   已加载 {len(manager.instances)} 个实例")

    # 2. 列出所有实例
    print("\n[2] 列出所有实例...")
    instances = manager.get_all_instances()
    for inst in instances:
        print(f"   - {inst.instance_id}: {inst.name} (状态: {inst.status.value})")
    #
    # # 3. 创建新实例
    # print("\n[3] 创建新实例...")
    # new_instance = await manager.create_instance(
    #     instance_id="test_lifecycle",
    #     name="生命周期测试",
    #     description="测试启动、重启、关闭流程",
    #     host="127.0.0.1",
    #     port=8999,
    #     web_host="127.0.0.1",
    #     web_port=9000,
    #     enable_webui=False,
    #     enable_socket=False,
    # )
    # print(f"   创建成功: {new_instance.instance_id}")
    #
    # 4. 启动实例
    print("\n[4] 启动实例 test_lifecycle...")
    success = await manager.start_instance("test_lifecycle")
    if success:
        instance = manager.get_instance("test_lifecycle")
        status = instance.status.value if hasattr(instance.status, 'value') else instance.status
        print(f"   启动成功! 状态: {status}")
    else:
        instance = manager.get_instance("test_lifecycle")
        if instance:
            print(f"   启动失败: {instance.error_message}")
        else:
            print("   启动失败: 实例不存在")
        return

    await asyncio.sleep(5)

    # 4. 启动实例
    print("\n[5] 启动实例 default...")
    success = await manager.start_instance("default")
    if success:
        instance2 = manager.get_instance("default")
        status = instance2.status.value if hasattr(instance2.status, 'value') else instance2.status
        print(f"   启动成功! 状态: {status}")
    else:
        instance2 = manager.get_instance("default")
        if instance2:
            print(f"   启动失败: {instance2.error_message}")
        else:
            print("   启动失败: 实例不存在")
        return


    # print("\n[4] 启动实例 default...")
    # success = await manager.start_instance("default")
    # if success:
    #     instance2 = manager.get_instance("default")
    #     status = instance2.status.value if hasattr(instance2.status, 'value') else instance2.status
    #     print(f"   启动成功! 状态: {status}")
    # else:
    #     instance2 = manager.get_instance("default")
    #     if instance2:
    #         print(f"   启动失败: {instance2.error_message}")
    #     else:
    #         print("   启动失败: 实例不存在")
    #     return
    #
    # print("\n[4] 启动实例 default...")
    # success = await manager.start_instance("default")
    # if success:
    #     instance2 = manager.get_instance("default")
    #     status = instance2.status.value if hasattr(instance2.status, 'value') else instance2.status
    #     print(f"   启动成功! 状态: {status}")
    # else:
    #     instance2 = manager.get_instance("default")
    #     if instance2:
    #         print(f"   启动失败: {instance2.error_message}")
    #     else:
    #         print("   启动失败: 实例不存在")
    #     return


    # # 5. 等待几秒
    # print("\n[5] 等待 3 秒...")
    print("    结束 等待 ing")

    await asyncio.sleep(30000000)
    #
    # # 6. 查看运行中的实例
    # print("\n[6] 运行中的实例...")
    # running = manager.get_running_instances()
    # for inst in running:
    #     print(f"   - {inst.instance_id}: {inst.name} (状态: {inst.status.value})")
    #
    # # 7. 停止实例
    # print("\n[7] 停止实例 test_lifecycle...")
    # success = await manager.stop_instance("test_lifecycle")
    # if success:
    #     instance = manager.get_instance("test_lifecycle")
    #     print(f"   停止成功! 状态: {instance.status.value}")
    # else:
    #     print(f"   停止失败")
    #
    # # 8. 再次启动
    # print("\n[8] 再次启动实例 test_lifecycle...")
    # success = await manager.start_instance("test_lifecycle")
    # if success:
    #     instance = manager.get_instance("test_lifecycle")
    #     print(f"   启动成功! 状态: {instance.status.value}")
    # await asyncio.sleep(2)
    #
    # # 9. 停止
    # print("\n[9] 再次停止实例 test_lifecycle...")
    # success = await manager.stop_instance("test_lifecycle")
    # print(f"   停止成功! 状态: {manager.get_instance('test_lifecycle').status.value}")
    #
    # # 10. 查看创建的文件
    # print("\n[10] 查看创建的文件...")
    # print(f"\n   数据目录: {data_root}")
    # print(f"   实例目录: {os.path.join(data_root, 'instances', 'test_lifecycle')}")
    #
    # print("\n   目录结构:")
    # for root, dirs, files in os.walk(os.path.join(data_root, "instances", "test_lifecycle")):
    #     level = root.replace(data_root, "").count(os.sep)
    #     indent = "   " + "  " * level
    #     print(f"{indent}{os.path.basename(root)}/")
    #     subindent = "   " + "  " * (level + 1)
    #     for file in files:
    #         print(f"{subindent}{file}")
    #
    # print("\n   config/instances_meta.json 内容:")
    # meta_path = os.path.join(data_root, "config", "instances_meta.json")
    # if os.path.exists(meta_path):
    #     import json
    #     with open(meta_path, "r", encoding="utf-8") as f:
    #         content = json.load(f)
    #     print(f"   {json.dumps(content, indent=4, ensure_ascii=False)[:500]}...")
    #
    # print("\n   config/instances/test_lifecycle.toml 内容:")
    # config_path = os.path.join(data_root, "config", "instances", "test_lifecycle.toml")
    # if os.path.exists(config_path):
    #     with open(config_path, "r", encoding="utf-8") as f:
    #         content = f.read()
    #     print(f"   {content[:500]}...")
    #
    # # 11. 使用全局函数测试
    # print("\n[11] 使用全局函数测试...")
    # print(f"   list_instances(): {list_instances()[:2]}")
    #
    # print("\n" + "=" * 60)
    # print("测试完成!")
    # print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_real_lifecycle())
