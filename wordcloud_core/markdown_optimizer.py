import re
import threading
import time
from typing import Any, Callable, Optional

from astrbot.api import logger


class T2IConfigReader:
    """AstrBot t2i 配置读取器

    参考 iris_memory 项目实现，从 AstrBot 主配置读取 t2i 相关设置。
    使用缓存机制避免频繁读取配置。

    Args:
        context: AstrBot Context 对象
        cache_ttl: 配置缓存 TTL（秒），默认 60 秒
    """

    def __init__(self, context: Any, cache_ttl: float = 60.0) -> None:
        self._context = context
        self._cache_ttl = cache_ttl
        self._cache: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def get_t2i_enabled(self) -> bool:
        """获取文转图开关状态

        Returns:
            是否启用文转图
        """
        return self._get_cached("t2i_enabled", self._read_t2i_enabled)

    def get_t2i_threshold(self) -> int:
        """获取文转图字数阈值

        Returns:
            触发转图的最小字数
        """
        return self._get_cached("t2i_threshold", self._read_t2i_threshold)

    def invalidate_cache(self) -> None:
        """清除配置缓存"""
        with self._lock:
            self._cache.clear()

    def _get_cached(self, key: str, reader: Callable[[], Any]) -> Any:
        """带缓存的配置读取"""
        with self._lock:
            now = time.time()
            if key in self._cache:
                value, expire_time = self._cache[key]
                if now < expire_time:
                    return value

            value = reader()
            self._cache[key] = (value, now + self._cache_ttl)
            return value

    def _read_t2i_enabled(self) -> bool:
        """从 AstrBot 主配置读取 t2i 开关"""
        try:
            config = self._context.get_config()
            return bool(config.get("t2i", False))
        except Exception:
            return False

    def _read_t2i_threshold(self) -> int:
        """从 AstrBot 主配置读取 t2i 阈值"""
        try:
            config = self._context.get_config()
            return int(config.get("t2i_word_threshold", 150))
        except Exception:
            return 150


class MarkdownOptimizer:
    """Markdown 优化器

    针对长文本转图片场景，优化 Markdown 格式以确保正确渲染。

    主要解决的问题：
    1. 换行失效：Markdown 中单个换行符不会产生新段落，需要双换行或两空格+换行
    2. 列表渲染：确保列表项之间有正确的换行
    3. 代码块：保护代码块内容不被误处理

    Args:
        t2i_reader: T2IConfigReader 实例
    """

    _CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
    _INLINE_CODE_RE = re.compile(r"`[^`]+`")
    _LIST_ITEM_RE = re.compile(r"^[*\-+]\s+.+$", re.MULTILINE)
    _ORDERED_LIST_RE = re.compile(r"^\d+\.\s+.+$", re.MULTILINE)

    def __init__(self, t2i_reader: Optional[T2IConfigReader] = None) -> None:
        self._t2i_reader = t2i_reader

    def optimize_for_t2i(self, text: str) -> str:
        """为转图片场景优化 Markdown

        当文本将被转换为图片时，优化 Markdown 格式以确保正确渲染。

        Args:
            text: 原始文本

        Returns:
            优化后的文本
        """
        if not text:
            return text

        code_blocks: list[str] = []
        inline_codes: list[str] = []

        def save_code_block(m: re.Match) -> str:
            idx = len(code_blocks)
            code_blocks.append(m.group(0))
            return f"\x00CODE_BLOCK_{idx}\x00"

        def save_inline_code(m: re.Match) -> str:
            idx = len(inline_codes)
            inline_codes.append(m.group(0))
            return f"\x00INLINE_CODE_{idx}\x00"

        result = self._CODE_BLOCK_RE.sub(save_code_block, text)
        result = self._INLINE_CODE_RE.sub(save_inline_code, result)

        result = self._fix_line_breaks(result)
        result = self._fix_list_items(result)

        for idx, code in enumerate(code_blocks):
            result = result.replace(f"\x00CODE_BLOCK_{idx}\x00", code)
        for idx, code in enumerate(inline_codes):
            result = result.replace(f"\x00INLINE_CODE_{idx}\x00", code)

        return result

    def _fix_line_breaks(self, text: str) -> str:
        """修复换行问题

        Markdown 渲染规则：
        - 单个换行符：不产生新段落，连续文本
        - 两空格+换行：产生换行（<br>）
        - 双换行：产生新段落

        对于长文本转图片，我们采用以下策略：
        - 保持原有的双换行（段落分隔）
        - 单换行转为双换行，确保每行独立显示
        """
        lines = text.split("\n")
        result_lines: list[str] = []
        prev_empty = False

        for line in lines:
            is_empty = not line.strip()

            if is_empty:
                result_lines.append("")
                prev_empty = True
            elif prev_empty:
                result_lines.append(line)
                prev_empty = False
            else:
                if result_lines and result_lines[-1]:
                    prev_line = result_lines[-1]
                    if self._is_list_item(prev_line) or self._is_list_item(line):
                        result_lines.append(line)
                    else:
                        result_lines.append("")
                        result_lines.append(line)
                else:
                    result_lines.append(line)
                prev_empty = False

        return "\n".join(result_lines)

    def _fix_list_items(self, text: str) -> str:
        """修复列表项格式

        确保列表项之间有正确的换行，避免渲染时挤在一起。
        """
        lines = text.split("\n")
        result: list[str] = []

        for i, line in enumerate(lines):
            result.append(line)

            if self._is_list_item(line) and i + 1 < len(lines):
                next_line = lines[i + 1]
                if next_line.strip() and not self._is_list_item(next_line):
                    result.append("")

        return "\n".join(result)

    def _is_list_item(self, line: str) -> bool:
        """判断是否为列表项"""
        stripped = line.strip()
        return bool(
            self._LIST_ITEM_RE.match(stripped) or
            self._ORDERED_LIST_RE.match(stripped)
        )

    def should_optimize(self, text: str, use_t2i: Optional[bool] = None) -> bool:
        """判断是否需要优化

        Args:
            text: 待检测文本
            use_t2i: 消息级 use_t2i_ 覆盖（None 跟随全局设置）

        Returns:
            是否需要优化
        """
        if not text:
            return False

        if use_t2i is True:
            return True

        if use_t2i is False:
            return False

        if self._t2i_reader is None:
            return False

        if not self._t2i_reader.get_t2i_enabled():
            return False

        threshold = self._t2i_reader.get_t2i_threshold()
        return len(text) >= threshold


def optimize_text_for_t2i(
    text: str,
    t2i_reader: Optional[T2IConfigReader] = None,
    use_t2i: Optional[bool] = None,
) -> str:
    """便捷函数：为转图片场景优化文本

    Args:
        text: 原始文本
        t2i_reader: T2I 配置读取器
        use_t2i: 是否强制使用 t2i

    Returns:
        优化后的文本
    """
    optimizer = MarkdownOptimizer(t2i_reader)
    if optimizer.should_optimize(text, use_t2i):
        return optimizer.optimize_for_t2i(text)
    return text
