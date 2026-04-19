import os

from astrbot.api.star import StarTools

_PLUGIN_DIR_NAME = "astrbot_plugin_wordcloud"


def _get_data_dir() -> str:
    data_dir = StarTools.get_data_dir(_PLUGIN_DIR_NAME)
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir)


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
        custom = self.get("wordcloud_font_path", "")
        if custom and os.path.isfile(custom):
            return custom
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts", "SourceHanSans.otf")

    @property
    def stopwords_path(self) -> str:
        custom = self.get("wordcloud_stopwords_path", "")
        if custom and os.path.isfile(custom):
            return custom
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "stopwords", "stop_words.txt")

    @property
    def user_dict_path(self) -> str:
        custom = self.get("wordcloud_user_dict_path", "")
        if custom and os.path.isfile(custom):
            return custom
        return ""

    @property
    def pos_whitelist(self) -> set:
        raw = self.get("wordcloud_pos_whitelist", "n,nr,ns,nt,nz,v,vd,vn,a,ad,an,d")
        if not raw:
            return set()
        return {p.strip() for p in raw.split(",") if p.strip()}

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
