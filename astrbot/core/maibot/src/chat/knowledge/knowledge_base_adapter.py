"""
AstrBot 知识库适配器

通过 IPC 与主进程通信，调用 AstrBot 的知识库检索功能。
由于 maibot 运行在子进程中，无法直接访问主进程的 KnowledgeBaseManager，
因此通过进程间队列发送检索请求，由主进程执行检索并返回结果。

IPC 通信流程：
1. 子进程通过 output_queue 发送 kb_retrieve 请求给主进程
2. 主进程处理请求，调用 KnowledgeBaseManager.retrieve()
3. 主进程通过 input_queue 发送 kb_retrieve_result 响应给子进程
"""

import asyncio
import time
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass

from .global_logger import logger


@dataclass
class KBRetrievalResult:
    """知识库检索结果"""
    content: str          # 段落内容
    score: float          # 相似度分数
    kb_name: str          # 来源知识库名称
    doc_name: str = ""    # 来源文档名称


# 全局响应缓存：存储从主进程收到的检索结果
# key: request_id, value: response payload
_response_cache: Dict[str, Dict] = {}
_response_cache_lock = asyncio.Lock()


def cache_kb_response(request_id: str, payload: Dict) -> None:
    """缓存知识库检索响应（由命令循环调用）

    Args:
        request_id: 请求 ID
        payload: 响应数据
    """
    _response_cache[request_id] = payload
    logger.debug(f"[KB Adapter] 缓存响应: request_id={request_id}")


class KnowledgeBaseAdapter:
    """AstrBot 知识库适配器

    通过 IPC 与主进程通信，实现知识库检索功能。
    """

    # 类变量：存储 IPC 队列引用
    _output_queue = None  # 发送请求到主进程（子进程的 output_queue）
    _instance_id: str = "default"

    def __init__(
        self,
        kb_names: Optional[List[str]] = None,
        fusion_top_k: int = 5,
        return_top_k: int = 20,
        timeout: float = 10.0,
    ):
        """初始化适配器

        Args:
            kb_names: 要检索的知识库名称列表，None 表示使用全部知识库
            fusion_top_k: 融合后返回的结果数量
            return_top_k: 从知识库检索的结果数量
            timeout: 检索超时时间（秒）
        """
        self.kb_names = kb_names or []
        self.fusion_top_k = fusion_top_k
        self.return_top_k = return_top_k
        self.timeout = timeout
        self._enabled = True

    @classmethod
    def set_ipc_queues(cls, output_queue, instance_id: str = "default"):
        """设置 IPC 队列（由子进程入口调用）

        Args:
            output_queue: 发送请求到主进程的队列（子进程的 output_queue）
            instance_id: 实例 ID
        """
        cls._output_queue = output_queue
        cls._instance_id = instance_id
        logger.info(f"[KB Adapter] IPC 队列已设置: instance_id={instance_id}")

    @classmethod
    def is_available(cls) -> bool:
        """检查适配器是否可用（IPC 队列是否已设置）"""
        return cls._output_queue is not None

    async def retrieve(
        self,
        query: str,
        kb_names: Optional[List[str]] = None,
        top_k: Optional[int] = None,
    ) -> List[KBRetrievalResult]:
        """从 AstrBot 知识库检索相关内容

        Args:
            query: 查询文本
            kb_names: 要检索的知识库名称列表，None 则使用初始化时的配置
            top_k: 返回结果数量，None 则使用初始化时的配置

        Returns:
            检索结果列表
        """
        if not self._enabled:
            logger.debug("[KB Adapter] 适配器已禁用")
            return []

        if not self.is_available():
            logger.warning("[KB Adapter] IPC 队列未设置，无法检索")
            return []

        # 使用参数或默认配置
        kb_names = kb_names or self.kb_names
        top_k = top_k or self.fusion_top_k

        # 即使 kb_names 为空，也发送请求到主进程，让主进程自动获取所有知识库
        if not kb_names:
            logger.debug("[KB Adapter] 未指定知识库，将请求主进程获取所有知识库")

        try:
            # 发送检索请求到主进程
            request_id = f"kb_{int(time.time() * 1000)}_{id(self)}"
            request = {
                "type": "kb_retrieve",
                "payload": {
                    "request_id": request_id,
                    "instance_id": self._instance_id,
                    "query": query,
                    "kb_names": kb_names,
                    "top_k_fusion": top_k,
                    "top_m_final": self.return_top_k,
                }
            }

            logger.debug(f"[KB Adapter] 发送检索请求: query={query[:50]}..., kb_names={kb_names}")
            self._output_queue.put_nowait(request)

            # 等待响应（从全局缓存中获取）
            start_time = time.time()
            while time.time() - start_time < self.timeout:
                # 检查缓存中是否有响应
                if request_id in _response_cache:
                    payload = _response_cache.pop(request_id)
                    if payload.get("success"):
                        results = payload.get("results", [])
                        logger.info(f"[KB Adapter] 检索成功，返回 {len(results)} 条结果")
                        return [
                            KBRetrievalResult(
                                content=r.get("content", ""),
                                score=r.get("score", 0.0),
                                kb_name=r.get("kb_name", ""),
                                doc_name=r.get("doc_name", ""),
                            )
                            for r in results
                        ]
                    else:
                        error = payload.get("error", "未知错误")
                        logger.warning(f"[KB Adapter] 检索失败: {error}")
                        return []

                await asyncio.sleep(0.05)

            logger.warning(f"[KB Adapter] 检索超时: {self.timeout}s")
            return []

        except Exception as e:
            logger.error(f"[KB Adapter] 检索异常: {e}")
            return []

    async def health_check(self) -> bool:
        """检查知识库是否可用"""
        return self.is_available() and self._enabled

    def enable(self):
        """启用适配器"""
        self._enabled = True
        logger.info("[KB Adapter] 适配器已启用")

    def disable(self):
        """禁用适配器"""
        self._enabled = False
        logger.info("[KB Adapter] 适配器已禁用")


# 全局适配器实例
_global_adapter: Optional[KnowledgeBaseAdapter] = None


def get_kb_adapter() -> Optional[KnowledgeBaseAdapter]:
    """获取全局知识库适配器实例"""
    return _global_adapter


def set_kb_adapter(adapter: KnowledgeBaseAdapter):
    """设置全局知识库适配器实例"""
    global _global_adapter
    _global_adapter = adapter
    logger.info("[KB Adapter] 全局适配器已设置")


def create_kb_adapter(
    kb_names: Optional[List[str]] = None,
    fusion_top_k: int = 5,
    return_top_k: int = 20,
    timeout: float = 10.0,
) -> KnowledgeBaseAdapter:
    """创建并设置全局知识库适配器

    Args:
        kb_names: 要检索的知识库名称列表
        fusion_top_k: 融合后返回的结果数量
        return_top_k: 从知识库检索的结果数量
        timeout: 检索超时时间

    Returns:
        创建的适配器实例
    """
    global _global_adapter
    _global_adapter = KnowledgeBaseAdapter(
        kb_names=kb_names,
        fusion_top_k=fusion_top_k,
        return_top_k=return_top_k,
        timeout=timeout,
    )
    return _global_adapter


__all__ = [
    "KnowledgeBaseAdapter",
    "KBRetrievalResult",
    "get_kb_adapter",
    "set_kb_adapter",
    "create_kb_adapter",
    "cache_kb_response",
]
