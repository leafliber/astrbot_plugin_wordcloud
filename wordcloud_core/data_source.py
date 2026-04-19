import os
import re
from collections import Counter
from typing import Optional

from wordcloud import WordCloud
import numpy as np

from astrbot.api import logger

from .config import Config

_CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_URL_PATTERN = re.compile(r"https?://\S+")
_AT_PATTERN = re.compile(r"@\S+")
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001f600-\U0001f64f"
    "\U0001f300-\U0001f5ff"
    "\U0001f680-\U0001f6ff"
    "\U0001f1e0-\U0001f1ff"
    "\U00002702-\U000027b0"
    "\U000024c2-\U0001f251"
    "]+",
    flags=re.UNICODE,
)


def _load_stopwords(path: str) -> set:
    if not path or not os.path.isfile(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def _pre_process(text: str) -> str:
    text = _URL_PATTERN.sub("", text)
    text = _AT_PATTERN.sub("", text)
    text = _EMOJI_PATTERN.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class SegEngine:
    def __init__(self, config: Config):
        self._config = config
        self._seg = None
        self._stopwords: set = set()
        self._group_segs: dict = {}
        self._ready: bool = False
        self._engine_type: str = "none"

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def engine_type(self) -> str:
        return self._engine_type

    def _init_pkuseg(self, user_dict: Optional[str] = None):
        import spacy_pkuseg as pkuseg

        kwargs = {
            "model_name": self._config.pkuseg_model,
            "postag": True,
        }
        dict_path = user_dict or self._config.user_dict_path
        if dict_path and os.path.isfile(dict_path):
            kwargs["user_dict"] = dict_path
        return pkuseg.pkuseg(**kwargs)

    def _init_jieba(self, user_dict: Optional[str] = None):
        import jieba
        import jieba.posseg

        dict_path = user_dict or self._config.user_dict_path
        if dict_path and os.path.isfile(dict_path):
            jieba.load_userdict(dict_path)
        return jieba.posseg

    def initialize(self):
        try:
            self._seg = self._init_pkuseg()
            self._engine_type = "pkuseg"
            logger.info(f"[WordCloud] pkuseg 初始化成功, model={self._config.pkuseg_model}")
        except Exception as e:
            logger.warning(f"[WordCloud] pkuseg 初始化失败: {e}，尝试退化到 jieba 分词")
            try:
                self._seg = self._init_jieba()
                self._engine_type = "jieba"
                logger.info("[WordCloud] 已退化到 jieba 分词引擎")
            except Exception as e2:
                logger.error(f"[WordCloud] jieba 初始化也失败: {e2}，分词引擎不可用")
                self._seg = None
                self._engine_type = "none"
                self._stopwords = _load_stopwords(self._config.stopwords_path)
                self._ready = True
                return

        self._stopwords = _load_stopwords(self._config.stopwords_path)
        self._ready = True

    def get_seg(self, group_key: Optional[str] = None):
        if group_key is None:
            return self._seg
        if group_key not in self._group_segs:
            dict_path = self._build_merged_dict(group_key)
            if self._engine_type == "pkuseg":
                self._group_segs[group_key] = self._init_pkuseg(user_dict=dict_path)
            else:
                self._group_segs[group_key] = self._init_jieba(user_dict=dict_path)
        return self._group_segs[group_key]

    def _build_merged_dict(self, group_key: str) -> Optional[str]:
        global_dict = self._config.user_dict_path
        group_dict_path = os.path.join(self._config.dict_dir, f"dict-{group_key}.txt")
        if not os.path.isfile(group_dict_path) and (not global_dict or not os.path.isfile(global_dict)):
            return None
        lines = []
        if global_dict and os.path.isfile(global_dict):
            with open(global_dict, "r", encoding="utf-8") as f:
                lines.extend(f.readlines())
        if os.path.isfile(group_dict_path):
            with open(group_dict_path, "r", encoding="utf-8") as f:
                lines.extend(f.readlines())
        if not lines:
            return None
        merged_path = os.path.join(self._config.dict_dir, f"merged-{group_key}.txt")
        with open(merged_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return merged_path

    def invalidate_group_cache(self, group_key: str):
        self._group_segs.pop(group_key, None)

    def cut(self, text: str, group_key: Optional[str] = None) -> list[tuple[str, str]]:
        seg = self.get_seg(group_key)
        if seg is None:
            return []
        try:
            result = seg.cut(text)
            if self._engine_type == "jieba":
                return [(w.word, w.flag) for w in result]
            return list(result)
        except Exception as e:
            logger.error(f"[WordCloud] 分词失败: {e}")
            return []

    def terminate(self):
        self._group_segs.clear()


_JIEBA_POS_WHITELIST = {"n", "nr", "ns", "nt", "nz", "v", "vd", "vn", "a", "ad", "an", "d"}
_PKUSEG_POS_WHITELIST = {"n", "v", "a", "d", "i", "j", "l", "nz", "nr", "ns", "nt"}


def analyse_message(
    messages: list,
    seg_engine: SegEngine,
    config: Config,
    group_key: Optional[str] = None,
    pos_filter: Optional[str] = None,
) -> Counter:
    word_counter: Counter = Counter()
    if seg_engine.engine_type == "jieba":
        pos_whitelist = _JIEBA_POS_WHITELIST
    else:
        pos_whitelist = _PKUSEG_POS_WHITELIST
    min_len = config.min_word_length
    stopwords = seg_engine._stopwords

    for msg in messages:
        text = msg.message_str if hasattr(msg, "message_str") else str(msg)
        if not text:
            continue
        text = _pre_process(text)
        if not text:
            continue

        words_with_pos = seg_engine.cut(text, group_key)
        for word, pos in words_with_pos:
            if len(word) < min_len:
                continue
            if word in stopwords:
                continue
            
            has_chinese = bool(_CHINESE_PATTERN.search(word))
            
            if not has_chinese:
                if len(word) > 20 or _URL_PATTERN.search(word):
                    continue
                if word.isdigit() or word.replace('.', '').replace('-', '').isdigit():
                    continue

            if pos_filter is not None:
                if not pos.startswith(pos_filter):
                    continue
            else:
                if pos_whitelist and pos not in pos_whitelist:
                    continue

            word_counter[word] += 1

    return word_counter


def generate_wordcloud(
    word_counter: Counter,
    config: Config,
    colormap: Optional[str] = None,
    mask_image: Optional[np.ndarray] = None,
) -> Optional[bytes]:
    if not word_counter:
        return None

    font_path = config.font_path
    if font_path is None:
        logger.warning("[WordCloud] 字体路径为空，词云可能无法正确显示中文")

    wc_kwargs = {
        "width": config.width,
        "height": config.height,
        "background_color": config.background_color,
        "max_words": config.max_words,
        "colormap": colormap or config.colormap,
        "collocations": False,
    }
    
    if font_path:
        wc_kwargs["font_path"] = font_path

    if mask_image is not None:
        wc_kwargs["mask"] = mask_image
        wc_kwargs["contour_width"] = 0

    try:
        wc = WordCloud(**wc_kwargs)
        wc.generate_from_frequencies(word_counter)
    except Exception as e:
        logger.error(f"[WordCloud] 词云生成失败: {e}")
        return None

    img = wc.to_image()

    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()
