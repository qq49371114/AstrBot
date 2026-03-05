"""
知识库查询管理器

提供知识库查询的状态管理和结果存储。
"""

import asyncio
import os
import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
from astrbot.core.maibot.src.common.logger import get_logger
from astrbot.core.maibot.src.chat.knowledge.knowledge_base_adapter import get_kb_adapter, KBRetrievalResult

logger = get_logger("kb_query_manager")

# 全局知识库配置
_kb_config: Dict[str, Any] = {}


def set_kb_config(config: Dict[str, Any]) -> None:
    """设置知识库配置

    Args:
        config: 知识库配置字典
    """
    global _kb_config
    _kb_config = config
    logger.info(f"知识库配置已设置: {config}")


def get_kb_config() -> Dict[str, Any]:
    """获取知识库配置

    Returns:
        Dict[str, Any]: 知识库配置字典
    """
    return _kb_config


class KBQueryStatus(Enum):
    """知识库查询状态"""
    IDLE = "idle"           # 无查询
    QUERYING = "querying"   # 查询中
    COMPLETED = "completed" # 已完成
    FAILED = "failed"       # 失败


@dataclass
class KBQueryResult:
    """知识库查询结果"""
    status: KBQueryStatus = KBQueryStatus.IDLE
    result_text: str = ""   # 格式化后的结果文本
    error_msg: str = ""     # 错误信息
    query_time: float = 0   # 查询耗时（秒）


def _merge_results(all_results: List[List[KBRetrievalResult]], max_results: int = 5) -> List[KBRetrievalResult]:
    """合并多个查询的结果，去重并按分数排序"""
    seen_contents: set = set()
    merged: List[KBRetrievalResult] = []
    all_items: List[KBRetrievalResult] = []
    for results in all_results:
        if results:
            all_items.extend(results)
    all_items.sort(key=lambda x: x.score, reverse=True)
    for item in all_items:
        content_key = item.content[:200] if item.content else ""
        if content_key and content_key not in seen_contents:
            seen_contents.add(content_key)
            merged.append(item)
            if len(merged) >= max_results:
                break
    return merged


async def execute_kb_query(
    chat_stream,
    kb_keywords: Optional[List[str]],
) -> KBQueryResult:
    """执行知识库查询

    Args:
        chat_stream: 聊天流对象
        kb_keywords: 查询关键词列表

    Returns:
        KBQueryResult: 查询结果
    """
    result = KBQueryResult(status=KBQueryStatus.QUERYING)
    start_time = time.time()

    # 构造日志前缀
    try:
        group_info = chat_stream.group_info
        user_info = chat_stream.user_info
        if group_info is not None and getattr(group_info, "group_name", None):
            stream_name = group_info.group_name.strip() or str(group_info.group_id)
        elif user_info is not None and getattr(user_info, "user_nickname", None):
            stream_name = user_info.user_nickname.strip() or str(user_info.user_id)
        else:
            stream_name = chat_stream.stream_id
    except Exception:
        stream_name = chat_stream.stream_id
    log_prefix = f"[{stream_name}] " if stream_name else ""

    logger.info(f"{log_prefix}知识库查询启动，kb_keywords={kb_keywords}")

    # 检查关键词
    if not kb_keywords:
        result.status = KBQueryStatus.IDLE
        logger.info(f"{log_prefix}无 kb_keywords，跳过查询")
        return result

    # 检查适配器
    adapter = get_kb_adapter()
    if adapter is None:
        result.status = KBQueryStatus.IDLE
        logger.info(f"{log_prefix}知识库适配器未配置，跳过查询")
        return result

    try:
        # 清理关键词
        queries: List[str] = []
        for kw in kb_keywords:
            if isinstance(kw, str) and kw.strip():
                cleaned = kw.strip()
                if cleaned not in queries:
                    queries.append(cleaned)

        if not queries:
            result.status = KBQueryStatus.IDLE
            return result

        queries = queries[:5]
        logger.info(f"{log_prefix}开始知识库查询，关键词: {queries}")

        # 并行执行查询
        async def retrieve_single(query: str) -> List[KBRetrievalResult]:
            try:
                return await adapter.retrieve(query)
            except Exception as e:
                logger.error(f"{log_prefix}查询 '{query}' 失败: {e}")
                return []

        all_results = await asyncio.gather(*[retrieve_single(q) for q in queries])
        merged_results = _merge_results(all_results, max_results=5)

        result.query_time = time.time() - start_time

        if not merged_results:
            result.status = KBQueryStatus.COMPLETED
            result.result_text = "资料库中没有参考结果，不回答或者含糊掩盖过去，不要编造数据"
            logger.info(f"{log_prefix}知识库查询无结果，耗时: {result.query_time:.3f}秒")
            return result

        # 格式化结果
        formatted = []
        for i, r in enumerate(merged_results, 1):
            formatted.append(f"第{i}条资料：{r.content} (相关度: {r.score:.2f}, 来源: {r.kb_name})")

        result.status = KBQueryStatus.COMPLETED
        result.result_text = "以下是从资料库中检索到的相关信息：\n" + "\n".join(formatted) + "\n请参考这些资料进行回复。\n"
        logger.info(f"{log_prefix}知识库查询成功，返回 {len(formatted)} 条结果，耗时: {result.query_time:.3f}秒")

    except Exception as e:
        result.status = KBQueryStatus.FAILED
        result.error_msg = str(e)
        logger.error(f"{log_prefix}知识库查询异常: {e}")

    return result


def get_querying_prompt() -> str:
    """获取"查询中"状态的提示词"""
    return "【系统提示】数据库正在查询中，请先告知用户你正在查询相关资料，让用户耐心等待，稍后会给出详细回复，要人性化多样化，简单回复活跃气氛。\n"


def get_result_prompt(kb_result: KBQueryResult) -> str:
    """获取查询结果的提示词

    Args:
        kb_result: 查询结果

    Returns:
        str: 格式化的提示词
    """
    if kb_result.status == KBQueryStatus.COMPLETED:
        return f"【数据库查询结果】\n{kb_result.result_text}\n请基于以上查询结果回复用户。\n"
    elif kb_result.status == KBQueryStatus.FAILED:
        return f"【数据库查询失败】{kb_result.error_msg}\n请告知用户查询出现问题。\n"
    else:
        return ""


def _get_long_thinking_enabled() -> bool:
    """获取知识库长思考模式是否启用

    Returns:
        bool: 是否启用长思考模式
    """
    global _kb_config
    return _kb_config.get("long_thinking_enabled", False)


def _get_data_txt_content() -> str:
    """获取知识库 data.txt 文件内容"""
    try:
        from astrbot.core.maibot.src.config.context import get_context
        context = get_context()
        # 修正路径：data/knowledge_base/data.txt
        data_txt_path = os.path.join(context.get_project_root(), "data.txt")
        logger.debug(f"尝试读取 data.txt，路径: {data_txt_path}")
        if os.path.exists(data_txt_path):
            with open(data_txt_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    logger.info(f"成功读取 data.txt，内容长度: {len(content)} 字符")
                    return f"\n\n【知识库基础资料】\n{content}\n"
        else:
            logger.warning(f"data.txt 文件不存在: {data_txt_path}")
        return ""
    except Exception as e:
        logger.warning(f"读取 data.txt 失败: {e}")
        return ""


def _build_long_thinking_prompt(
    kb_result: KBQueryResult,
    chat_history: List,
    current_message: str,
) -> str:
    """构建长思考模式的提示词

    Args:
        kb_result: 知识库查询结果
        chat_history: 聊天历史列表
        current_message: 当前用户消息

    Returns:
        str: 构造好的长思考提示词
    """
    # 添加知识库查询结果
    prompt_parts = [
        "【知识库检索结果】",
        kb_result.result_text,
    ]

    # 添加 data.txt 内容
    data_txt_content = _get_data_txt_content()
    if data_txt_content:
        prompt_parts.append(data_txt_content)

    # 添加聊天历史（最近10条）
    if chat_history:
        prompt_parts.append("\n【最近聊天记录】")
        # 格式化聊天历史
        formatted_history = []
        for msg in chat_history[-10:]:
            if hasattr(msg, "processed_plain_text"):
                # DatabaseMessages 没有 role 属性，需要通过其他方式判断
                # 检查是否有 user_id，如果有说明是用户消息，否则是机器人消息
                msg_text = msg.processed_plain_text or ""
                formatted_history.append(f": {msg_text}")
            elif isinstance(msg, dict):
                role = msg.get("role", "用户")
                content = msg.get("content", "")
                formatted_history.append(f"{role}: {content}")
        if formatted_history:
            prompt_parts.append("\n".join(formatted_history))

    # 添加当前用户消息
    if current_message:
        prompt_parts.append(f"\n【当前用户消息】\n{current_message}")

    # 添加指令
    prompt_parts.append("""
【任务】
请根据以上知识库检索结果、基础资料和聊天历史，给出答案和有关消息进行下一步操作。

要求：
1. 综合分析所有资料，给出准确、简洁的回答
2. 如果有多条相关信息，需要整合归纳
3. 只返回最终答案，不要返回思考过程
4. 如果知识库中没有相关信息，请明确告知用户
5. 信息要准确

【输出格式】
请直接输出答案，如果有多个要点请用简洁的方式列出。
""")

    return "\n".join(prompt_parts)


async def execute_kb_long_thinking(
    chat_stream,
    kb_keywords: Optional[List[str]],
    chat_history: List,
    current_message: str,
) -> KBQueryResult:
    """执行知识库长思考模式查询

    将检索结果、聊天历史、data.txt 内容发送给大模型，让大模型生成简洁的唯一结果。

    Args:
        chat_stream: 聊天流对象
        kb_keywords: 查询关键词列表
        chat_history: 聊天历史列表
        current_message: 当前用户消息

    Returns:
        KBQueryResult: 查询结果（包含大模型生成的处理后结果）
    """
    result = KBQueryResult(status=KBQueryStatus.QUERYING)
    start_time = time.time()

    # 构造日志前缀
    try:
        group_info = chat_stream.group_info
        user_info = chat_stream.user_info
        if group_info is not None and getattr(group_info, "group_name", None):
            stream_name = group_info.group_name.strip() or str(group_info.group_id)
        elif user_info is not None and getattr(user_info, "user_nickname", None):
            stream_name = user_info.user_nickname.strip() or str(user_info.user_id)
        else:
            stream_name = chat_stream.stream_id
    except Exception:
        stream_name = chat_stream.stream_id
    log_prefix = f"[{stream_name}] " if stream_name else ""

    logger.info(f"{log_prefix}知识库长思考模式查询启动，kb_keywords={kb_keywords}")

    # 先执行普通查询获取原始结果
    kb_result = await execute_kb_query(chat_stream, kb_keywords)
    if kb_result.status != KBQueryStatus.COMPLETED or not kb_result.result_text:
        result.status = kb_result.status
        result.result_text = kb_result.result_text
        result.error_msg = kb_result.error_msg
        result.query_time = time.time() - start_time
        # return result

    # 检查是否启用长思考模式
    if not _get_long_thinking_enabled():
        logger.info(f"{log_prefix}长思考模式未启用，使用普通查询结果")
        result.status = KBQueryStatus.COMPLETED
        result.result_text = kb_result.result_text
        result.query_time = time.time() - start_time
        return result

    try:
        # 构建长思考提示词
        long_thinking_prompt = _build_long_thinking_prompt(
            kb_result=kb_result,
            chat_history=chat_history,
            current_message=current_message,
        )

        # 打印完整提示词日志
        logger.info(f"{log_prefix}开始长思考模式，大模型处理中...")
        logger.info(f"{log_prefix}【发送给AI的完整提示词】\n{'-'*60}\n{long_thinking_prompt}\n{'-'*60}")

        # 调用大模型处理
        from astrbot.core.maibot.src.plugin_system.apis import llm_api
        from astrbot.core.maibot.src.config.config import model_config

        # 使用 replyer 模型配置
        success, response, reasoning, model_name = await llm_api.generate_with_model(
            prompt=long_thinking_prompt,
            model_config=model_config.model_task_config.replyer,
            request_type="kb_long_thinking",
        )

        result.query_time = time.time() - start_time

        if success and response:
            # 打印AI返回的原始内容
            logger.info(f"{log_prefix}【AI返回的原始内容】\n{'-'*60}\n{response}\n{'-'*60}")
            logger.info(f"{log_prefix}使用模型: {model_name}, 推理内容长度: {len(reasoning) if reasoning else 0}")

            # 清理模型返回内容，去除可能的 markdown 标记
            cleaned_response = response.strip()
            # 去除可能的 ``` 标记
            if cleaned_response.startswith("```"):
                lines = cleaned_response.split("\n")
                cleaned_response = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            cleaned_response = cleaned_response.strip()

            result.status = KBQueryStatus.COMPLETED
            result.result_text = f"【知识库综合分析结果】\n{cleaned_response}\n"
            logger.info(f"{log_prefix}长思考模式完成，耗时: {result.query_time:.3f}秒")
        else:
            # 大模型调用失败，回退到原始结果
            logger.warning(f"{log_prefix}长思考模式大模型调用失败，回退到原始结果")
            result.status = KBQueryStatus.COMPLETED
            result.result_text = kb_result.result_text

    except Exception as e:
        logger.error(f"{log_prefix}长思考模式异常: {e}")
        # 异常时回退到原始结果
        result.status = KBQueryStatus.COMPLETED
        result.result_text = kb_result.result_text
        result.query_time = time.time() - start_time

    return result
