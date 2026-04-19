import asyncio
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

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
from wordcloud_core.scheduler import add_schedule, remove_schedule, get_all_schedules


@register(
    name="astrbot_plugin_wordcloud",
    desc="群聊词云生成插件，基于 pkuseg 分词与词性标注",
    author="Leafiber",
    version="0.1.0",
)
class WordCloudPlugin(Star):
    _TIME_KEYWORD_MAP = {
        "today": "today",
        "yesterday": "yesterday",
        "this_week": "week",
        "last_week": None,
        "this_month": "month",
        "last_month": None,
        "this_year": None,
    }

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

    @asynccontextmanager
    async def _event_context(self, event: AstrMessageEvent):
        try:
            yield
        finally:
            event.stop_event()

    async def _reply(self, event: AstrMessageEvent, message: str):
        event.stop_event()
        return event.plain_result(message)

    async def _reply_yield(self, event: AstrMessageEvent, message: str):
        event.stop_event()
        yield event.plain_result(message)

    def _check_ready(self) -> Optional[str]:
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

    def _require_group(self, event: AstrMessageEvent) -> Optional[str]:
        group_key = self._get_group_key(event)
        if not group_key:
            return "仅限群聊使用"
        return None

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

    async def _send_wordcloud(
        self,
        event: AstrMessageEvent,
        messages: list,
        period_name: str,
        group_key: Optional[str] = None,
        pos_filter: Optional[str] = None,
        colormap_override: Optional[str] = None,
        title_suffix: str = "",
    ):
        err = self._check_ready()
        if err:
            async for r in self._reply_yield(event, err):
                yield r
            return

        if not messages:
            async for r in self._reply_yield(event, f"{period_name}暂无消息记录"):
                yield r
            return

        loop = asyncio.get_event_loop()
        word_counter = await loop.run_in_executor(
            self._executor,
            lambda: analyse_message(messages, self._seg_engine, self._config, group_key, pos_filter),
        )

        if not word_counter:
            async for r in self._reply_yield(event, f"{period_name}有效词语不足"):
                yield r
            return

        mask = self._mask_manager.get_mask(group_key)
        title = f"{period_name}{title_suffix}词云" if title_suffix else f"{period_name}词云"

        image_data = await loop.run_in_executor(
            self._executor,
            lambda: generate_wordcloud(word_counter, self._config, colormap_override, mask, title),
        )

        if not image_data:
            async for r in self._reply_yield(event, "词云生成失败"):
                yield r
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

        async for r in self._reply_yield(event, ""):
            yield r

    async def _wordcloud_command(
        self,
        event: AstrMessageEvent,
        time_keyword: str,
        period_name: str,
    ):
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, time_keyword, group_id)
        async for result in self._send_wordcloud(event, messages, period_name, group_key):
            yield result

    async def _pos_wordcloud_command(
        self,
        event: AstrMessageEvent,
        pos_filter: str,
        title_suffix: str,
    ):
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        colormap = getattr(self._config, f"pos_{pos_filter}_colormap", None) if len(pos_filter) == 1 else None
        if colormap is None and len(pos_filter) == 1:
            colormap_map = {"n": self._config.pos_noun_colormap, "v": self._config.pos_verb_colormap, "a": self._config.pos_adj_colormap, "d": self._config.pos_adv_colormap}
            colormap = colormap_map.get(pos_filter)
        messages = await self._get_messages(event, "today", group_id)
        async for result in self._send_wordcloud(
            event, messages, "今日", group_key,
            pos_filter=pos_filter, colormap_override=colormap, title_suffix=title_suffix,
        ):
            yield result

    async def _ranking_command(self, event: AstrMessageEvent, time_keyword: str, period_name: str):
        err = self._check_ready()
        if err:
            async for r in self._reply_yield(event, err):
                yield r
            return
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, time_keyword, group_id)
        ranking = compute_ranking(messages, self._config.ranking_limit, self._config.ranking_show_percentage)
        async for r in self._reply_yield(event, format_ranking(ranking, period_name)):
            yield r

    async def _pos_analysis_command(self, event: AstrMessageEvent, time_keyword: str, period_name: str):
        err = self._check_ready()
        if err:
            async for r in self._reply_yield(event, err):
                yield r
            return
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, time_keyword, group_id)
        if not messages:
            async for r in self._reply_yield(event, f"{period_name}暂无消息记录"):
                yield r
            return
        loop = asyncio.get_event_loop()
        pos_dist = await loop.run_in_executor(
            self._executor,
            lambda: analyze_pos_distribution(messages, self._seg_engine, self._config, group_key),
        )
        async for r in self._reply_yield(event, format_pos_report(pos_dist, period_name)):
            yield r

    async def _trend_command(self, event: AstrMessageEvent, curr_kw: str, prev_kw: str, curr_name: str, prev_name: str):
        err = self._check_ready()
        if err:
            async for r in self._reply_yield(event, err):
                yield r
            return
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        curr_messages = await self._get_messages(event, curr_kw, group_id)
        prev_messages = await self._get_messages(event, prev_kw, group_id)

        if not curr_messages and not prev_messages:
            async for r in self._reply_yield(event, "暂无足够数据生成热词趋势"):
                yield r
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
        async for r in self._reply_yield(event, format_trend_report(trend, curr_name, prev_name)):
            yield r

    @filter.command("今日词云")
    async def today_wordcloud(self, event: AstrMessageEvent):
        async for result in self._wordcloud_command(event, "today", "今日"):
            yield result

    @filter.command("昨日词云")
    async def yesterday_wordcloud(self, event: AstrMessageEvent):
        async for result in self._wordcloud_command(event, "yesterday", "昨日"):
            yield result

    @filter.command("本周词云")
    async def week_wordcloud(self, event: AstrMessageEvent):
        async for result in self._wordcloud_command(event, "this_week", "本周"):
            yield result

    @filter.command("上周词云")
    async def last_week_wordcloud(self, event: AstrMessageEvent):
        async for result in self._wordcloud_command(event, "last_week", "上周"):
            yield result

    @filter.command("本月词云")
    async def month_wordcloud(self, event: AstrMessageEvent):
        async for result in self._wordcloud_command(event, "this_month", "本月"):
            yield result

    @filter.command("上月词云")
    async def last_month_wordcloud(self, event: AstrMessageEvent):
        async for result in self._wordcloud_command(event, "last_month", "上月"):
            yield result

    @filter.command("年度词云")
    async def year_wordcloud(self, event: AstrMessageEvent):
        async for result in self._wordcloud_command(event, "this_year", "今年"):
            yield result

    @filter.command_group("词云")
    def wordcloud_group(self):
        pass

    @wordcloud_group.command("名词")
    async def noun_wordcloud(self, event: AstrMessageEvent):
        async for result in self._pos_wordcloud_command(event, "n", "名词"):
            yield result

    @wordcloud_group.command("动词")
    async def verb_wordcloud(self, event: AstrMessageEvent):
        async for result in self._pos_wordcloud_command(event, "v", "动词"):
            yield result

    @wordcloud_group.command("形容词")
    async def adj_wordcloud(self, event: AstrMessageEvent):
        async for result in self._pos_wordcloud_command(event, "a", "形容词"):
            yield result

    @wordcloud_group.command("副词")
    async def adv_wordcloud(self, event: AstrMessageEvent):
        async for result in self._pos_wordcloud_command(event, "d", "副词"):
            yield result

    @filter.command("今日排名")
    async def today_ranking(self, event: AstrMessageEvent):
        async for result in self._ranking_command(event, "today", "今日"):
            yield result

    @filter.command("本周排名")
    async def week_ranking(self, event: AstrMessageEvent):
        async for result in self._ranking_command(event, "this_week", "本周"):
            yield result

    @filter.command("本月排名")
    async def month_ranking(self, event: AstrMessageEvent):
        async for result in self._ranking_command(event, "this_month", "本月"):
            yield result

    @filter.command("今日词性分析")
    async def today_pos_analysis(self, event: AstrMessageEvent):
        async for result in self._pos_analysis_command(event, "today", "今日"):
            yield result

    @filter.command("本周词性分析")
    async def week_pos_analysis(self, event: AstrMessageEvent):
        async for result in self._pos_analysis_command(event, "this_week", "本周"):
            yield result

    @filter.command("本月词性分析")
    async def month_pos_analysis(self, event: AstrMessageEvent):
        async for result in self._pos_analysis_command(event, "this_month", "本月"):
            yield result

    @filter.command("今日热词")
    async def today_trend(self, event: AstrMessageEvent):
        async for result in self._trend_command(event, "today", "yesterday", "今日", "昨日"):
            yield result

    @filter.command("本周热词")
    async def week_trend(self, event: AstrMessageEvent):
        async for result in self._trend_command(event, "this_week", "last_week", "本周", "上周"):
            yield result

    @filter.command("本月热词")
    async def month_trend(self, event: AstrMessageEvent):
        async for result in self._trend_command(event, "this_month", "last_month", "本月", "上月"):
            yield result

    @filter.command("群聊画像")
    async def group_profile(self, event: AstrMessageEvent):
        err = self._check_ready()
        if err:
            async for r in self._reply_yield(event, err):
                yield r
            return
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None

        time_kw = "this_month"
        text = event.message_str.strip()
        if "本周" in text:
            time_kw = "this_week"

        period_name = format_period_name(time_kw)
        messages = await self._get_messages(event, time_kw, group_id)
        if not messages:
            async for r in self._reply_yield(event, f"{period_name}暂无消息记录"):
                yield r
            return

        loop = asyncio.get_event_loop()
        profile = await loop.run_in_executor(
            self._executor,
            lambda: build_group_profile(messages, self._seg_engine, self._config, group_key, period_name),
        )
        if profile is None:
            async for r in self._reply_yield(event, "画像生成失败"):
                yield r
            return
        async for r in self._reply_yield(event, format_group_profile(profile)):
            yield r

    @filter.command("我的风格")
    async def my_style(self, event: AstrMessageEvent):
        err = self._check_ready()
        if err:
            async for r in self._reply_yield(event, err):
                yield r
            return
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
            async for r in self._reply_yield(event, f"{period_name}暂无消息记录"):
                yield r
            return

        loop = asyncio.get_event_loop()
        style = await loop.run_in_executor(
            self._executor,
            lambda: build_personal_style(messages, sender_id, self._seg_engine, self._config, group_key, period_name),
        )
        if style is None:
            async for r in self._reply_yield(event, "未找到你的发言记录"):
                yield r
            return
        async for r in self._reply_yield(event, format_personal_style(style)):
            yield r

    @filter.command("添加词云词典")
    async def add_dict_word(self, event: AstrMessageEvent, word: str, pos: Optional[str] = None):
        group_key = self._get_group_key(event)
        err = self._require_group(event)
        if err:
            async for r in self._reply_yield(event, err):
                yield r
            return

        self._dict_manager.add_word(group_key, word, pos)
        self._seg_engine.invalidate_group_cache(group_key)

        msg = f"已添加词语「{word}」（词性: {pos}）到群级词典" if pos else f"已添加词语「{word}」到群级词典"
        async for r in self._reply_yield(event, msg):
            yield r

    @filter.command("删除词云词典")
    async def remove_dict_word(self, event: AstrMessageEvent, word: str):
        group_key = self._get_group_key(event)
        err = self._require_group(event)
        if err:
            async for r in self._reply_yield(event, err):
                yield r
            return

        if self._dict_manager.remove_word(group_key, word):
            self._seg_engine.invalidate_group_cache(group_key)
            msg = f"已从群级词典删除词语「{word}」"
        else:
            msg = f"群级词典中未找到词语「{word}」"
        async for r in self._reply_yield(event, msg):
            yield r

    @filter.command("查看词云词典")
    async def list_dict_words(self, event: AstrMessageEvent):
        group_key = self._get_group_key(event)
        err = self._require_group(event)
        if err:
            async for r in self._reply_yield(event, err):
                yield r
            return

        words = self._dict_manager.list_words(group_key)
        if not words:
            async for r in self._reply_yield(event, "群级词典为空"):
                yield r
            return

        lines = ["📋 群级词典内容:", ""]
        for w in words:
            lines.append(f"  • {w}")
        async for r in self._reply_yield(event, "\n".join(lines)):
            yield r

    @filter.command("开启词云每日定时发送")
    async def enable_schedule(self, event: AstrMessageEvent, time_str: str = "22:00"):
        group_key = self._get_group_key(event)
        err = self._require_group(event)
        if err:
            async for r in self._reply_yield(event, err):
                yield r
            return

        umo = event.unified_msg_origin
        group_id = event.message_obj.group_id or ""
        add_schedule(group_key, time_str, unified_msg_origin=umo, group_id=group_id)
        async for r in self._reply_yield(event, f"已开启每日 {time_str} 定时发送今日词云"):
            yield r

    @filter.command("关闭词云每日定时发送")
    async def disable_schedule(self, event: AstrMessageEvent):
        group_key = self._get_group_key(event)
        err = self._require_group(event)
        if err:
            async for r in self._reply_yield(event, err):
                yield r
            return

        if remove_schedule(group_key):
            msg = "已关闭每日定时发送词云"
        else:
            msg = "本群未开启定时发送"
        async for r in self._reply_yield(event, msg):
            yield r

    @filter.command("设置词云形状")
    async def set_mask(self, event: AstrMessageEvent):
        group_key = self._get_group_key(event)
        err = self._require_group(event)
        if err:
            async for r in self._reply_yield(event, err):
                yield r
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
            async for r in self._reply_yield(event, "请回复一张图片来设置词云形状"):
                yield r
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status == 200:
                        image_data = await resp.read()
                    else:
                        async for r in self._reply_yield(event, "图片下载失败"):
                            yield r
                        return
        except Exception as e:
            logger.error(f"[WordCloud] 下载遮罩图片失败: {e}")
            async for r in self._reply_yield(event, "图片下载失败"):
                yield r
            return

        self._mask_manager.save_mask(image_data, group_key)
        async for r in self._reply_yield(event, "已设置群级词云形状"):
            yield r

    @filter.command("删除词云形状")
    async def delete_mask(self, event: AstrMessageEvent):
        group_key = self._get_group_key(event)
        err = self._require_group(event)
        if err:
            async for r in self._reply_yield(event, err):
                yield r
            return

        if self._mask_manager.delete_mask(group_key):
            msg = "已删除群级词云形状"
        else:
            msg = "本群未设置词云形状"
        async for r in self._reply_yield(event, msg):
            yield r

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
