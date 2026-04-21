import asyncio
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
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
from wordcloud_core.compare import compare_users, format_compare_result
from wordcloud_core.dict_manager import DictManager
from wordcloud_core.mask_manager import MaskManager
from wordcloud_core.scheduler import add_schedule, remove_schedule, get_all_schedules
from wordcloud_core.commands import (
    _MR_TIME_MAP, _COLORMAP_MAP,
    parse_time_kw, parse_pos_kw, parse_common_args,
)


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
        if not self._get_group_key(event):
            return "仅限群聊使用"
        return None

    async def _get_recorder_api(self):
        if self._mr_api is None and self._api_retry_count < self._api_max_retry:
            try:
                star_meta = self.context.get_registered_star("astrbot_plugin_message_recorder")
                if star_meta is None:
                    self._api_retry_count += 1
                    return None
                plugin_instance = getattr(star_meta, "star_cls", None)
                if plugin_instance is None:
                    self._api_retry_count += 1
                    return None
                if hasattr(plugin_instance, "get_api"):
                    self._mr_api = plugin_instance.get_api()
                    if self._mr_api:
                        logger.info("[WordCloud] 已获取 message_recorder API")
                    else:
                        self._api_retry_count += 1
                else:
                    self._api_retry_count += 1
            except Exception as e:
                self._api_retry_count += 1
                logger.warning(f"[WordCloud] 获取 message_recorder API 失败: {e}")
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
        mr_time = _MR_TIME_MAP.get(time_keyword)
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
        pos_name: Optional[str] = None,
    ):
        err = self._check_ready()
        if err:
            yield event.plain_result(err)
            return
        if not messages:
            yield event.plain_result(f"{period_name}暂无消息记录")
            return
        loop = asyncio.get_event_loop()
        word_counter = await loop.run_in_executor(
            self._executor,
            lambda: analyse_message(messages, self._seg_engine, self._config, group_key, pos_filter),
        )
        if not word_counter:
            yield event.plain_result(f"{period_name}有效词语不足")
            return
        mask = self._mask_manager.get_mask(group_key)
        colormap = None
        if pos_filter and pos_filter in _COLORMAP_MAP:
            colormap = getattr(self._config, _COLORMAP_MAP[pos_filter], None)
        image_data = await loop.run_in_executor(
            self._executor,
            lambda: generate_wordcloud(word_counter, self._config, colormap, mask),
        )
        if not image_data:
            yield event.plain_result("词云生成失败")
            return
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(image_data)
            temp_path = f.name
        event.track_temporary_local_file(temp_path)
        yield event.image_result(temp_path)

    @filter.command("词云", alias={"wc", "wordcloud"})
    async def cmd_wordcloud(self, event: AstrMessageEvent):
        event.should_call_llm(True)
        text = event.message_str.strip()
        args = parse_common_args(text)
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, args.time_kw, group_id)
        async for result in self._send_wordcloud(
            event, messages, args.period_name, group_key,
            pos_filter=args.pos_filter, pos_name=args.pos_name,
        ):
            yield result

    @filter.command("发言排名", alias={"排名", "排行榜", "谁最活跃"})
    async def cmd_ranking(self, event: AstrMessageEvent):
        event.should_call_llm(True)
        err = self._check_ready()
        if err:
            yield event.plain_result(err)
            return
        text = event.message_str.strip()
        time_kw, period_name = parse_time_kw(text)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, time_kw, group_id)
        ranking = compute_ranking(messages, self._config.ranking_limit, self._config.ranking_show_percentage)
        yield event.plain_result(format_ranking(ranking, period_name))

    @filter.command("词性分析", alias={"词性", "词类统计"})
    async def cmd_pos(self, event: AstrMessageEvent):
        event.should_call_llm(True)
        err = self._check_ready()
        if err:
            yield event.plain_result(err)
            return
        text = event.message_str.strip()
        time_kw, period_name = parse_time_kw(text)
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        messages = await self._get_messages(event, time_kw, group_id)
        if not messages:
            yield event.plain_result(f"{period_name}暂无消息记录")
            return
        loop = asyncio.get_event_loop()
        pos_dist = await loop.run_in_executor(
            self._executor,
            lambda: analyze_pos_distribution(messages, self._seg_engine, self._config, group_key),
        )
        yield event.plain_result(format_pos_report(pos_dist, period_name))

    @filter.command("热词趋势", alias={"热词", "趋势", "涨跌"})
    async def cmd_trend(self, event: AstrMessageEvent):
        event.should_call_llm(True)
        err = self._check_ready()
        if err:
            yield event.plain_result(err)
            return
        text = event.message_str.strip()
        time_kw, period_name = parse_time_kw(text)
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        prev_map = {
            "today": ("yesterday", "昨日"),
            "yesterday": ("today", "今日"),
            "this_week": ("last_week", "上周"),
            "last_week": ("this_week", "本周"),
            "this_month": ("last_month", "上月"),
            "last_month": ("this_month", "本月"),
            "this_year": ("last_month", "上月"),
        }
        prev_kw, prev_name = prev_map.get(time_kw, ("last_month", "上月"))
        curr_messages = await self._get_messages(event, time_kw, group_id)
        prev_messages = await self._get_messages(event, prev_kw, group_id)
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
        yield event.plain_result(format_trend_report(trend, period_name, prev_name))

    @filter.command("群画像", alias={"画像", "群聊画像", "群体画像"})
    async def cmd_profile(self, event: AstrMessageEvent):
        event.should_call_llm(True)
        err = self._check_ready()
        if err:
            yield event.plain_result(err)
            return
        text = event.message_str.strip()
        time_kw, period_name = parse_time_kw(text)
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
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

    @filter.command("我的画像", alias={"我的", "个人画像", "我的风格"})
    async def cmd_my_style(self, event: AstrMessageEvent):
        event.should_call_llm(True)
        err = self._check_ready()
        if err:
            yield event.plain_result(err)
            return
        text = event.message_str.strip()
        time_kw, period_name = parse_time_kw(text)
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None
        sender_id = event.message_obj.sender.user_id if event.message_obj.sender else ""
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

    @filter.command("词云词典", alias={"词典", "自定义词"})
    async def cmd_dict(self, event: AstrMessageEvent):
        event.should_call_llm(True)
        err = self._require_group(event)
        if err:
            yield event.plain_result(err)
            return
        group_key = self._get_group_key(event)
        text = event.message_str.strip()
        words = text.split()
        op = None
        word = None
        pos = None
        for w in words[1:]:
            if w in ("添加", "删除"):
                op = w
            elif word is None:
                word = w
            elif pos is None and len(w) <= 2:
                pos = w
        if op == "添加":
            if not word:
                yield event.plain_result("请指定要添加的词语")
                return
            self._dict_manager.add_word(group_key, word, pos)
            self._seg_engine.invalidate_group_cache(group_key)
            msg = f"已添加词语「{word}」" + (f"（词性: {pos}）" if pos else "") + "到群级词典"
            yield event.plain_result(msg)
        elif op == "删除":
            if not word:
                yield event.plain_result("请指定要删除的词语")
                return
            if self._dict_manager.remove_word(group_key, word):
                self._seg_engine.invalidate_group_cache(group_key)
                msg = f"已从群级词典删除词语「{word}」"
            else:
                msg = f"群级词典中未找到词语「{word}」"
            yield event.plain_result(msg)
        else:
            words_list = self._dict_manager.list_words(group_key)
            if not words_list:
                yield event.plain_result("群级词典为空")
                return
            lines = ["📋 群级词典内容:", ""]
            for w in words_list:
                lines.append(f"  • {w}")
            yield event.plain_result("\n".join(lines))

    @filter.command("词云定时", alias={"定时", "定时任务", "自动词云"})
    async def cmd_schedule(self, event: AstrMessageEvent):
        event.should_call_llm(True)
        err = self._require_group(event)
        if err:
            yield event.plain_result(err)
            return
        group_key = self._get_group_key(event)
        text = event.message_str.strip()
        words = text.split()
        op = None
        time_str = "22:00"
        for w in words[1:]:
            if w in ("开启", "关闭"):
                op = w
            elif ":" in w or "：" in w:
                time_str = w.replace("：", ":")
        if op == "开启":
            umo = event.unified_msg_origin
            group_id = event.message_obj.group_id or ""
            add_schedule(group_key, time_str, unified_msg_origin=umo, group_id=group_id)
            yield event.plain_result(f"已开启每日 {time_str} 定时发送今日词云")
        else:
            if remove_schedule(group_key):
                msg = "已关闭每日定时发送词云"
            else:
                msg = "本群未开启定时发送"
            yield event.plain_result(msg)

    @filter.command("词云形状", alias={"形状", "遮罩", "mask"})
    async def cmd_mask(self, event: AstrMessageEvent):
        event.should_call_llm(True)
        err = self._require_group(event)
        if err:
            yield event.plain_result(err)
            return
        group_key = self._get_group_key(event)
        text = event.message_str.strip()
        words = text.split()
        is_delete = "删除" in words
        if is_delete:
            if self._mask_manager.delete_mask(group_key):
                msg = "已删除群级词云形状"
            else:
                msg = "本群未设置词云形状"
            yield event.plain_result(msg)
        else:
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
            self._mask_manager.save_mask(image_data, group_key)
            yield event.plain_result("已设置群级词云形状")

    @filter.command("比较词云", alias={"对比", "比较"})
    async def cmd_compare(self, event: AstrMessageEvent):
        event.should_call_llm(True)
        err = self._check_ready()
        if err:
            yield event.plain_result(err)
            return
        err = self._require_group(event)
        if err:
            yield event.plain_result(err)
            return

        mentioned_users = []
        for comp in (event.message_obj.message or []):
            comp_type = type(comp).__name__
            if comp_type == "At":
                user_id = getattr(comp, "qq", None) or getattr(comp, "user_id", None)
                if user_id:
                    mentioned_users.append(str(user_id))

        my_sender_id = event.get_sender_id()

        if len(mentioned_users) == 0:
            yield event.plain_result("请 @ 一位或两位用户进行比较，例如：比较词云 @用户A 或 比较词云 @用户A @用户B")
            return

        if len(mentioned_users) == 1:
            sender_id_1 = mentioned_users[0]
            sender_id_2 = my_sender_id
        else:
            sender_id_1 = mentioned_users[0]
            sender_id_2 = mentioned_users[1]

        text = event.message_str.strip()
        time_kw, period_name = parse_time_kw(text)
        group_key = self._get_group_key(event)
        group_id = event.message_obj.group_id or None

        messages = await self._get_messages(event, time_kw, group_id)
        if not messages:
            yield event.plain_result(f"{period_name}暂无消息记录")
            return

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            self._executor,
            lambda: compare_users(
                messages, sender_id_1, sender_id_2,
                self._seg_engine, self._config, group_key, period_name
            ),
        )

        if result is None:
            yield event.plain_result("未找到被 @ 用户的发言记录")
            return

        yield event.plain_result(format_compare_result(result))

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
            messages = await api.query(group_id=group_id, time="today", limit=50000)
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
            lambda: generate_wordcloud(word_counter, self._config, None, mask),
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
