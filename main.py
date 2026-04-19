import asyncio
import os
import sys
import tempfile
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

# 确保插件目录在 sys.path 中
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

import aiohttp
from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register

from wordcloud_core.config import Config
from wordcloud_core.data_source import SegEngine, analyse_message, generate_wordcloud
from wordcloud_core.time_utils import get_time_range, format_period_name
from wordcloud_core.ranking import compute_ranking, format_ranking
from wordcloud_core.pos_analyzer import analyze_pos_distribution, format_pos_report
from wordcloud_core.trend import compute_trend, format_trend_report
from wordcloud_core.profile import (
    build_group_profile, build_personal_style,
    format_group_profile, format_personal_style,
)
from wordcloud_core.dict_manager import DictManager
from wordcloud_core.mask_manager import MaskManager
from wordcloud_core.scheduler import add_schedule, remove_schedule, get_schedule, get_all_schedules


@register(
    name="astrbot_plugin_wordcloud",
    desc="群聊词云生成插件，基于 pkuseg 分词与词性标注",
    author="Leafiber",
    version="0.1.0",
)
class WordCloudPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self._raw_config = config
        self._config = Config(config)
        self._seg_engine = SegEngine(self._config)
        self._dict_manager = DictManager(self._config)
        self._mask_manager = MaskManager(self._config)
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._mr_api = None
        self._schedule_task: Optional[asyncio.Task] = None
        self._api_retry_count: int = 0
        self._api_max_retry: int = 5

    async def _get_recorder_api(self):
        if self._mr_api is None and self._api_retry_count < self._api_max_retry:
            try:
                star_meta = self.context.get_registered_star("astrbot_plugin_message_recorder")
                logger.debug(f"[WordCloud] get_registered_star 返回: {star_meta}")
                
                if star_meta is None:
                    self._api_retry_count += 1
                    logger.warning(f"[WordCloud] 未找到 message_recorder 插件 (重试 {self._api_retry_count}/{self._api_max_retry})")
                    return None
                
                plugin_instance = getattr(star_meta, "star_cls", None)
                logger.debug(f"[WordCloud] star_cls: {plugin_instance}")
                
                if plugin_instance is None:
                    self._api_retry_count += 1
                    logger.warning(f"[WordCloud] message_recorder 插件实例为 None (重试 {self._api_retry_count}/{self._api_max_retry})")
                    return None
                
                if hasattr(plugin_instance, "get_api"):
                    self._mr_api = plugin_instance.get_api()
                    if self._mr_api:
                        logger.info("[WordCloud] 已获取 message_recorder API")
                    else:
                        self._api_retry_count += 1
                        logger.warning(f"[WordCloud] message_recorder 插件未正确初始化 (重试 {self._api_retry_count}/{self._api_max_retry})")
                else:
                    self._api_retry_count += 1
                    logger.warning(f"[WordCloud] 插件实例没有 get_api 方法 (重试 {self._api_retry_count}/{self._api_max_retry})")
                    
            except Exception as e:
                self._api_retry_count += 1
                logger.warning(f"[WordCloud] 获取 message_recorder API 失败: {e} (重试 {self._api_retry_count}/{self._api_max_retry})")
        return self._mr_api

    async def _bg_init_recorder_api(self):
        for i in range(self._api_max_retry):
            if self._mr_api is not None:
                break
            await self._get_recorder_api()
            if self._mr_api is None and i < self._api_max_retry - 1:
                await asyncio.sleep(2)
        if self._mr_api is None:
            logger.error("[WordCloud] 无法连接 message_recorder 插件，请确保已安装并启用")

    async def initialize(self):
        asyncio.create_task(self._bg_init_seg_engine())
        asyncio.create_task(self._bg_init_recorder_api())

        logger.info("[WordCloud] 插件初始化完成（后台加载中）")
        self._schedule_task = asyncio.create_task(self._schedule_loop())

    async def _bg_init_seg_engine(self):
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self._executor, self._seg_engine.initialize)
            logger.info(f"[WordCloud] 分词引擎就绪: {self._seg_engine.engine_type}")
        except Exception as e:
            logger.error(f"[WordCloud] 分词引擎初始化失败: {e}")

    async def terminate(self):
        if self._schedule_task:
            self._schedule_task.cancel()
        self._seg_engine.terminate()
        self._executor.shutdown(wait=False)

    def _check_ready(self, event: AstrMessageEvent) -> Optional[str]:
        if not self._seg_engine.ready:
            return "分词引擎正在加载中，请稍后再试"
        if self._seg_engine.engine_type == "none":
            return "分词引擎不可用，请联系管理员"
        return None

    def _get_group_key(self, event: AstrMessageEvent) -> Optional[str]:
        group_id = event.message_obj.group_id
        if not group_id:
            return None
        try:
            platform = event.get_platform_name() or "unknown"
        except Exception:
            platform = "unknown"
        return f"{platform}-{group_id}"

    _TIME_KEYWORD_MAP = {
        "today": "today",
        "yesterday": "yesterday",
        "this_week": "week",
        "last_week": None,
        "this_month": "month",
        "last_month": None,
        "this_year": None,
    }

    async def _get_messages(
        self,
        event: AstrMessageEvent,
        time_keyword: str,
        group_id: Optional[str] = None,
        sender_id: Optional[str] = None,
    ) -> list:
        api = await self._get_recorder_api()
        if api is None:
            return []

        mr_time = self._TIME_KEYWORD_MAP.get(time_keyword)
        kwargs: dict = {"limit": 50000}

        if mr_time:
            kwargs["time"] = mr_time
        else:
            start_time, end_time = get_time_range(time_keyword)
            kwargs["start_time"] = start_time
            kwargs["end_time"] = end_time

        if group_id:
            kwargs["group_id"] = group_id
        if sender_id:
            kwargs["sender_id"] = sender_id

        try:
            return await api.query(**kwargs)
        except Exception as e:
            logger.error(f"[WordCloud] 获取消息失败: {e}")
            return []

    async def _send_wordcloud_direct(
        self,
        event: AstrMessageEvent,
        messages: list,
        period_name: str,
        group_key: Optional[str] = None,
        pos_filter: Optional[str] = None,
        colormap_override: Optional[str] = None,
        title_suffix: str = "",
    ):
        if not self._seg_engine.ready:
            return

        if not messages:
            return

        loop = asyncio.get_event_loop()
        word_counter = await loop.run_in_executor(
            self._executor,
            lambda: analyse_message(messages, self._seg_engine, self._config, group_key, pos_filter),
        )

        if not word_counter:
            return

        mask = self._mask_manager.get_mask(group_key)
        title = f"{period_name}{title_suffix}词云" if title_suffix else f"{period_name}词云"

        image_data = await loop.run_in_executor(
            self._executor,
            lambda: generate_wordcloud(word_counter, self._config, colormap_override, mask, title),
        )

        if not image_data:
            return

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(image_data)
            temp_path = f.name

        try:
            umo = event.unified_msg_origin
            chain = MessageChain().file_image(temp_path)
            await self.context.send_message(umo, chain)
        except Exception as e:
            logger.error(f"[WordCloud] 发送词云失败: {e}")
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    @filter.command("今日词云")
    async def today_wordcloud(self, event: AstrMessageEvent):
        '''生成今日群聊词云'''
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "today", group_id)
        await self._send_wordcloud_direct(event, messages, "今日", group_key)

    @filter.command("昨日词云")
    async def yesterday_wordcloud(self, event: AstrMessageEvent):
        '''生成昨日群聊词云'''
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "yesterday", group_id)
        await self._send_wordcloud_direct(event, messages, "昨日", group_key)

    @filter.command("本周词云")
    async def week_wordcloud(self, event: AstrMessageEvent):
        '''生成本周群聊词云'''
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "this_week", group_id)
        await self._send_wordcloud_direct(event, messages, "本周", group_key)

    @filter.command("上周词云")
    async def last_week_wordcloud(self, event: AstrMessageEvent):
        '''生成上周群聊词云'''
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "last_week", group_id)
        await self._send_wordcloud_direct(event, messages, "上周", group_key)

    @filter.command("本月词云")
    async def month_wordcloud(self, event: AstrMessageEvent):
        '''生成本月群聊词云'''
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "this_month", group_id)
        await self._send_wordcloud_direct(event, messages, "本月", group_key)

    @filter.command("上月词云")
    async def last_month_wordcloud(self, event: AstrMessageEvent):
        '''生成上月群聊词云'''
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "last_month", group_id)
        await self._send_wordcloud_direct(event, messages, "上月", group_key)

    @filter.command("年度词云")
    async def year_wordcloud(self, event: AstrMessageEvent):
        '''生成年度群聊词云'''
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "this_year", group_id)
        await self._send_wordcloud_direct(event, messages, "今年", group_key)

    @filter.command_group("词云")
    def wordcloud_group(self):
        '''词云相关指令组'''
        pass

    @wordcloud_group.command("名词")
    async def noun_wordcloud(self, event: AstrMessageEvent):
        '''生成名词词云'''
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "today", group_id)
        await self._send_wordcloud_direct(
            event, messages, "今日", group_key,
            pos_filter="n", colormap_override=self._config.pos_noun_colormap,
            title_suffix="名词",
        )

    @wordcloud_group.command("动词")
    async def verb_wordcloud(self, event: AstrMessageEvent):
        '''生成动词词云'''
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "today", group_id)
        await self._send_wordcloud_direct(
            event, messages, "今日", group_key,
            pos_filter="v", colormap_override=self._config.pos_verb_colormap,
            title_suffix="动词",
        )

    @wordcloud_group.command("形容词")
    async def adj_wordcloud(self, event: AstrMessageEvent):
        '''生成形容词词云'''
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "today", group_id)
        await self._send_wordcloud_direct(
            event, messages, "今日", group_key,
            pos_filter="a", colormap_override=self._config.pos_adj_colormap,
            title_suffix="形容词",
        )

    @wordcloud_group.command("副词")
    async def adv_wordcloud(self, event: AstrMessageEvent):
        '''生成副词词云'''
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "today", group_id)
        await self._send_wordcloud_direct(
            event, messages, "今日", group_key,
            pos_filter="d", colormap_override=self._config.pos_adv_colormap,
            title_suffix="副词",
        )

    @filter.command("今日排名")
    async def today_ranking(self, event: AstrMessageEvent):
        '''查看今日发言排名'''
        err = self._check_ready(event)
        if err:
            yield event.plain_result(err); return
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "today", group_id)
        ranking = compute_ranking(messages, self._config.ranking_limit, self._config.ranking_show_percentage)
        yield event.plain_result(format_ranking(ranking, "今日"))

    @filter.command("本周排名")
    async def week_ranking(self, event: AstrMessageEvent):
        '''查看本周发言排名'''
        err = self._check_ready(event)
        if err:
            yield event.plain_result(err); return
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "this_week", group_id)
        ranking = compute_ranking(messages, self._config.ranking_limit, self._config.ranking_show_percentage)
        yield event.plain_result(format_ranking(ranking, "本周"))

    @filter.command("本月排名")
    async def month_ranking(self, event: AstrMessageEvent):
        '''查看本月发言排名'''
        err = self._check_ready(event)
        if err:
            yield event.plain_result(err); return
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "this_month", group_id)
        ranking = compute_ranking(messages, self._config.ranking_limit, self._config.ranking_show_percentage)
        yield event.plain_result(format_ranking(ranking, "本月"))

    @filter.command("今日词性分析")
    async def today_pos_analysis(self, event: AstrMessageEvent):
        '''查看今日词性分布分析'''
        err = self._check_ready(event)
        if err:
            yield event.plain_result(err); return
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "today", group_id)
        if not messages:
            yield event.plain_result("今日暂无消息记录")
            return
        loop = asyncio.get_event_loop()
        pos_dist = await loop.run_in_executor(
            self._executor,
            lambda: analyze_pos_distribution(messages, self._seg_engine, self._config, group_key),
        )
        yield event.plain_result(format_pos_report(pos_dist, "今日"))

    @filter.command("本周词性分析")
    async def week_pos_analysis(self, event: AstrMessageEvent):
        '''查看本周词性分布分析'''
        err = self._check_ready(event)
        if err:
            yield event.plain_result(err); return
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "this_week", group_id)
        if not messages:
            yield event.plain_result("本周暂无消息记录")
            return
        loop = asyncio.get_event_loop()
        pos_dist = await loop.run_in_executor(
            self._executor,
            lambda: analyze_pos_distribution(messages, self._seg_engine, self._config, group_key),
        )
        yield event.plain_result(format_pos_report(pos_dist, "本周"))

    @filter.command("本月词性分析")
    async def month_pos_analysis(self, event: AstrMessageEvent):
        '''查看本月词性分布分析'''
        err = self._check_ready(event)
        if err:
            yield event.plain_result(err); return
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, "this_month", group_id)
        if not messages:
            yield event.plain_result("本月暂无消息记录")
            return
        loop = asyncio.get_event_loop()
        pos_dist = await loop.run_in_executor(
            self._executor,
            lambda: analyze_pos_distribution(messages, self._seg_engine, self._config, group_key),
        )
        yield event.plain_result(format_pos_report(pos_dist, "本月"))

    @filter.command("今日热词")
    async def today_trend(self, event: AstrMessageEvent):
        '''查看今日热词趋势'''
        err = self._check_ready(event)
        if err:
            yield event.plain_result(err); return
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        curr_messages = await self._get_messages(event, "today", group_id)
        prev_messages = await self._get_messages(event, "yesterday", group_id)

        if not curr_messages and not prev_messages:
            yield event.plain_result("暂无足够数据生成热词趋势")
            return

        loop = asyncio.get_event_loop()
        freq_curr = await loop.run_in_executor(
            self._executor,
            lambda: analyse_message(curr_messages, self._seg_engine, self._config, group_key),
        )
        freq_prev = await loop.run_in_executor(
            self._executor,
            lambda: analyse_message(prev_messages, self._seg_engine, self._config, group_key),
        )

        trend = compute_trend(
            freq_curr, freq_prev,
            threshold=self._config.trend_threshold,
            emerging_limit=self._config.trend_emerging_limit,
            declining_limit=self._config.trend_declining_limit,
        )
        yield event.plain_result(format_trend_report(trend, "今日", "昨日"))

    @filter.command("本周热词")
    async def week_trend(self, event: AstrMessageEvent):
        '''查看本周热词趋势'''
        err = self._check_ready(event)
        if err:
            yield event.plain_result(err); return
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        curr_messages = await self._get_messages(event, "this_week", group_id)
        prev_messages = await self._get_messages(event, "last_week", group_id)

        if not curr_messages and not prev_messages:
            yield event.plain_result("暂无足够数据生成热词趋势")
            return

        loop = asyncio.get_event_loop()
        freq_curr = await loop.run_in_executor(
            self._executor,
            lambda: analyse_message(curr_messages, self._seg_engine, self._config, group_key),
        )
        freq_prev = await loop.run_in_executor(
            self._executor,
            lambda: analyse_message(prev_messages, self._seg_engine, self._config, group_key),
        )

        trend = compute_trend(
            freq_curr, freq_prev,
            threshold=self._config.trend_threshold,
            emerging_limit=self._config.trend_emerging_limit,
            declining_limit=self._config.trend_declining_limit,
        )
        yield event.plain_result(format_trend_report(trend, "本周", "上周"))

    @filter.command("本月热词")
    async def month_trend(self, event: AstrMessageEvent):
        '''查看本月热词趋势'''
        err = self._check_ready(event)
        if err:
            yield event.plain_result(err); return
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        curr_messages = await self._get_messages(event, "this_month", group_id)
        prev_messages = await self._get_messages(event, "last_month", group_id)

        if not curr_messages and not prev_messages:
            yield event.plain_result("暂无足够数据生成热词趋势")
            return

        loop = asyncio.get_event_loop()
        freq_curr = await loop.run_in_executor(
            self._executor,
            lambda: analyse_message(curr_messages, self._seg_engine, self._config, group_key),
        )
        freq_prev = await loop.run_in_executor(
            self._executor,
            lambda: analyse_message(prev_messages, self._seg_engine, self._config, group_key),
        )

        trend = compute_trend(
            freq_curr, freq_prev,
            threshold=self._config.trend_threshold,
            emerging_limit=self._config.trend_emerging_limit,
            declining_limit=self._config.trend_declining_limit,
        )
        yield event.plain_result(format_trend_report(trend, "本月", "上月"))

    @filter.command("群聊画像")
    async def group_profile(self, event: AstrMessageEvent):
        '''查看群聊语言画像'''
        err = self._check_ready(event)
        if err:
            yield event.plain_result(err); return
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None

        time_kw = "this_month"
        text = event.message_str.strip()
        if "本周" in text:
            time_kw = "this_week"

        period_name = format_period_name(time_kw)
        messages = await self._get_messages(event, time_kw, group_id)
        if not messages:
            yield event.plain_result(f"{period_name}暂无消息记录")
            return

        loop = asyncio.get_event_loop()
        profile = await loop.run_in_executor(
            self._executor,
            lambda: build_group_profile(messages, self._seg_engine, self._config, group_key, period_name),
        )
        if profile is None:
            yield event.plain_result("画像生成失败")
            return
        yield event.plain_result(format_group_profile(profile))

    @filter.command("我的风格")
    async def my_style(self, event: AstrMessageEvent):
        '''查看个人语言风格'''
        err = self._check_ready(event)
        if err:
            yield event.plain_result(err); return
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        sender_id = event.message_obj.sender.user_id if event.message_obj.sender else ""

        time_kw = "this_month"
        text = event.message_str.strip()
        if "本周" in text:
            time_kw = "this_week"

        period_name = format_period_name(time_kw)
        messages = await self._get_messages(event, time_kw, group_id)
        if not messages:
            yield event.plain_result(f"{period_name}暂无消息记录")
            return

        loop = asyncio.get_event_loop()
        style = await loop.run_in_executor(
            self._executor,
            lambda: build_personal_style(messages, sender_id, self._seg_engine, self._config, group_key, period_name),
        )
        if style is None:
            yield event.plain_result("未找到你的发言记录")
            return
        yield event.plain_result(format_personal_style(style))

    @filter.command("添加词云词典")
    async def add_dict_word(self, event: AstrMessageEvent, word: str, pos: Optional[str] = None):
        '''添加词语到群级词典（管理员）'''
        group_key = self._get_group_key(event)
        if not group_key:
            yield event.plain_result("仅限群聊使用")
            return

        self._dict_manager.add_word(group_key, word, pos)
        self._seg_engine.invalidate_group_cache(group_key)

        if pos:
            yield event.plain_result(f"已添加词语「{word}」（词性: {pos}）到群级词典")
        else:
            yield event.plain_result(f"已添加词语「{word}」到群级词典")

    @filter.command("删除词云词典")
    async def remove_dict_word(self, event: AstrMessageEvent, word: str):
        '''从群级词典删除词语（管理员）'''
        group_key = self._get_group_key(event)
        if not group_key:
            yield event.plain_result("仅限群聊使用")
            return

        if self._dict_manager.remove_word(group_key, word):
            self._seg_engine.invalidate_group_cache(group_key)
            yield event.plain_result(f"已从群级词典删除词语「{word}」")
        else:
            yield event.plain_result(f"群级词典中未找到词语「{word}」")

    @filter.command("查看词云词典")
    async def list_dict_words(self, event: AstrMessageEvent):
        '''查看群级词典内容'''
        group_key = self._get_group_key(event)
        if not group_key:
            yield event.plain_result("仅限群聊使用")
            return

        words = self._dict_manager.list_words(group_key)
        if not words:
            yield event.plain_result("群级词典为空")
            return

        lines = ["📋 群级词典内容:", ""]
        for w in words:
            lines.append(f"  • {w}")
        yield event.plain_result("\n".join(lines))

    @filter.command("开启词云每日定时发送")
    async def enable_schedule(self, event: AstrMessageEvent, time_str: str = "22:00"):
        '''开启每日定时发送词云（默认22:00）'''
        group_key = self._get_group_key(event)
        if not group_key:
            yield event.plain_result("仅限群聊使用")
            return

        umo = event.unified_msg_origin
        group_id = event.message_obj.group_id or ""
        add_schedule(group_key, time_str, unified_msg_origin=umo, group_id=group_id)
        yield event.plain_result(f"已开启每日 {time_str} 定时发送今日词云")

    @filter.command("关闭词云每日定时发送")
    async def disable_schedule(self, event: AstrMessageEvent):
        '''关闭每日定时发送词云'''
        group_key = self._get_group_key(event)
        if not group_key:
            yield event.plain_result("仅限群聊使用")
            return

        if remove_schedule(group_key):
            yield event.plain_result("已关闭每日定时发送词云")
        else:
            yield event.plain_result("本群未开启定时发送")

    @filter.command("设置词云形状")
    async def set_mask(self, event: AstrMessageEvent):
        '''设置群级词云遮罩（回复一张图片）'''
        group_key = self._get_group_key(event)
        if not group_key:
            yield event.plain_result("仅限群聊使用")
            return

        image_url = None
        for comp in (event.message_obj.message or []):
            if hasattr(comp, "url") and comp.url:
                image_url = comp.url
                break
            if hasattr(comp, "path") and comp.path:
                image_url = comp.path
                break

        if not image_url:
            yield event.plain_result("请回复一张图片来设置词云形状")
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status == 200:
                        image_data = await resp.read()
                    else:
                        yield event.plain_result("图片下载失败")
                        return
        except Exception as e:
            logger.error(f"[WordCloud] 下载遮罩图片失败: {e}")
            yield event.plain_result("图片下载失败")
            return

        path = self._mask_manager.save_mask(image_data, group_key)
        yield event.plain_result(f"已设置群级词云形状")

    @filter.command("删除词云形状")
    async def delete_mask(self, event: AstrMessageEvent):
        '''删除群级词云遮罩'''
        group_key = self._get_group_key(event)
        if not group_key:
            yield event.plain_result("仅限群聊使用")
            return

        if self._mask_manager.delete_mask(group_key):
            yield event.plain_result("已删除群级词云形状")
        else:
            yield event.plain_result("本群未设置词云形状")

    async def _schedule_loop(self):
        last_sent_date: dict[str, str] = {}

        while True:
            try:
                await asyncio.sleep(60)

                now = datetime.now()
                current_time = now.strftime("%H:%M")
                current_date = now.strftime("%Y-%m-%d")

                schedules = get_all_schedules()
                for group_key, schedule_info in schedules.items():
                    if not schedule_info.get("enabled", True):
                        continue
                    if schedule_info.get("time") != current_time:
                        continue
                    if last_sent_date.get(group_key) == current_date:
                        continue

                    last_sent_date[group_key] = current_date
                    await self._send_scheduled_wordcloud(group_key, schedule_info)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WordCloud] 定时任务异常: {e}")

    async def _send_scheduled_wordcloud(self, group_key: str, schedule_info: dict):
        api = await self._get_recorder_api()
        if api is None:
            return

        umo = schedule_info.get("umo", "")
        group_id = schedule_info.get("group_id", "")

        if not umo:
            logger.warning(f"[WordCloud] 定时任务缺少 unified_msg_origin: {group_key}")
            return

        try:
            messages = await api.query(
                group_id=group_id,
                time="today",
                limit=50000,
            )
        except Exception as e:
            logger.error(f"[WordCloud] 定时任务获取消息失败: {e}")
            return

        if not messages:
            return

        loop = asyncio.get_event_loop()
        word_counter = await loop.run_in_executor(
            self._executor,
            lambda: analyse_message(messages, self._seg_engine, self._config, group_key),
        )

        if not word_counter:
            return

        mask = self._mask_manager.get_mask(group_key)
        image_data = await loop.run_in_executor(
            self._executor,
            lambda: generate_wordcloud(word_counter, self._config, None, mask, "今日词云"),
        )

        if not image_data:
            return

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(image_data)
            temp_path = f.name

        try:
            chain = MessageChain().message("每日词云已送达！").file_image(temp_path)
            await self.context.send_message(umo, chain)
        except Exception as e:
            logger.error(f"[WordCloud] 定时发送词云失败: {e}")
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
