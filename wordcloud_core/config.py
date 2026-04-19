import os

from astrbot.api.star import StarTools
from astrbot.api import logger

_PLUGIN_DIR_NAME = "astrbot_plugin_wordcloud"

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_data_dir() -> str:
    data_dir = StarTools.get_data_dir(_PLUGIN_DIR_NAME)
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir)


def _get_plugin_dir() -> str:
    return _PLUGIN_DIR


class Config:
    def __init__(self, config):
        self._config = config

    def get(self, key: str, default=None):
        return self._config.get(key, default)

    @property
    def pkuseg_model(self) -> str:
        return self.get("wordcloud_pkuseg_model", "web")

    @property
    def min_word_length(self) -> int:
        return self.get("wordcloud_min_word_length", 2)

    @property
    def max_words(self) -> int:
        return self.get("wordcloud_max_words", 200)

    @property
    def width(self) -> int:
        return self.get("wordcloud_width", 800)

    @property
    def height(self) -> int:
        return self.get("wordcloud_height", 600)

    @property
    def background_color(self) -> str:
        return self.get("wordcloud_background_color", "white")

    @property
    def colormap(self) -> str:
        return self.get("wordcloud_colormap", "viridis")

    @property
    def font_path(self) -> str:
        file_list = self.get("wordcloud_font_file", [])
        if file_list and isinstance(file_list, list) and len(file_list) > 0:
            path = file_list[0]
            if os.path.isfile(path):
                logger.debug(f"[WordCloud] 使用上传的字体: {path}")
                return path
        custom = self.get("wordcloud_font_path", "")
        if custom and os.path.isfile(custom):
            logger.debug(f"[WordCloud] 使用自定义字体: {custom}")
            return custom
        
        default_font = os.path.join(_PLUGIN_DIR, "fonts", "HarmonyOS_Sans_SC_Regular.ttf")
        if os.path.isfile(default_font):
            logger.debug(f"[WordCloud] 使用默认字体: {default_font}")
            return default_font
        
        logger.warning(f"[WordCloud] 默认字体不存在: {default_font}，尝试系统字体")
        system_fonts = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "C:\\Windows\\Fonts\\msyh.ttc",
            "C:\\Windows\\Fonts\\simhei.ttf",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ]
        for sys_font in system_fonts:
            if os.path.isfile(sys_font):
                logger.info(f"[WordCloud] 使用系统字体: {sys_font}")
                return sys_font
        
        logger.error("[WordCloud] 未找到任何可用字体，词云可能无法正确显示中文")
        return None

    @property
    def stopwords_path(self) -> str:
        file_list = self.get("wordcloud_stopwords_file", [])
        if file_list and isinstance(file_list, list) and len(file_list) > 0:
            path = file_list[0]
            if os.path.isfile(path):
                return path
        custom = self.get("wordcloud_stopwords_path", "")
        if custom and os.path.isfile(custom):
            return custom
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "stopwords", "stop_words.txt")

    @property
    def user_dict_path(self) -> str:
        file_list = self.get("wordcloud_user_dict_file", [])
        if file_list and isinstance(file_list, list) and len(file_list) > 0:
            path = file_list[0]
            if os.path.isfile(path):
                return path
        custom = self.get("wordcloud_user_dict_path", "")
        if custom and os.path.isfile(custom):
            return custom
        return ""

    @property
    def ranking_limit(self) -> int:
        return self.get("wordcloud_ranking_limit", 10)

    @property
    def ranking_show_percentage(self) -> bool:
        return self.get("wordcloud_ranking_show_percentage", True)

    @property
    def pos_noun_colormap(self) -> str:
        return self.get("wordcloud_pos_noun_colormap", "Blues")

    @property
    def pos_verb_colormap(self) -> str:
        return self.get("wordcloud_pos_verb_colormap", "Greens")

    @property
    def pos_adj_colormap(self) -> str:
        return self.get("wordcloud_pos_adj_colormap", "Oranges")

    @property
    def pos_adv_colormap(self) -> str:
        return self.get("wordcloud_pos_adv_colormap", "Purples")

    @property
    def trend_threshold(self) -> float:
        return self.get("wordcloud_trend_threshold", 0.5)

    @property
    def trend_emerging_limit(self) -> int:
        return self.get("wordcloud_trend_emerging_limit", 10)

    @property
    def trend_declining_limit(self) -> int:
        return self.get("wordcloud_trend_declining_limit", 5)

    @property
    def profile_top_words(self) -> int:
        return self.get("wordcloud_profile_top_words", 5)

    @property
    def style_adj_threshold(self) -> float:
        return self.get("wordcloud_style_adj_threshold", 0.15)

    @property
    def style_verb_threshold(self) -> float:
        return self.get("wordcloud_style_verb_threshold", 0.30)

    @property
    def style_noun_threshold(self) -> float:
        return self.get("wordcloud_style_noun_threshold", 0.40)

    @property
    def data_dir(self) -> str:
        return _get_data_dir()

    @property
    def mask_dir(self) -> str:
        d = os.path.join(_get_data_dir(), "masks")
        os.makedirs(d, exist_ok=True)
        return d

    @property
    def dict_dir(self) -> str:
        d = os.path.join(_get_data_dir(), "dicts")
        os.makedirs(d, exist_ok=True)
        return d
