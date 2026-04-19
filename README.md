<div align="center">

# 🌟 AstrBot 词云插件 🌟

</div>

<div align="center">
  <img src="https://count.getloli.com/get/@astrbot-plugin-wordcloud?theme=moebooru" alt="访问次数" />
</div>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.1.0-pink.svg" alt="版本" />
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="许可证" />
  <img src="https://img.shields.io/badge/pkuseg-分词引擎-green.svg" />
  <img src="https://img.shields.io/badge/AstrBot-v4.0+-orange.svg" />
  <img src="https://img.shields.io/badge/Python-3.9+-yellow.svg" />
</p>

<p align="center">
  <strong>✨ 基于 pkuseg 的群聊词云生成插件，支持词性分析、热词趋势、语言画像等丰富功能 ✨</strong>
</p>

---

## 🌌 项目特色

- 📊 **多维度词云**：今日/昨日/本周/上周/本月/上月/年度词云
- 🎯 **词性词云**：名词/动词/形容词/副词，分类展示群聊话题
- 📈 **热词趋势**：对比分析新兴/衰退话题
- 🏆 **发言排名**：展示群聊活跃度排行
- 🔍 **词性分析**：统计词类分布，了解群聊语言风格
- 🎨 **语言画像**：群聊语言画像 + 个人风格分析
- 📅 **定时发送**：每日自动推送词云
- 🖼️ **自定义形状**：设置群级词云遮罩
- 📝 **群级词典**：添加专业术语，提高分词精度
- 🎨 **丰富配置**：颜色、字体、背景等高度可定制

---

## 📦 安装依赖

1. **前置插件**：需要先安装 [`astrbot_plugin_message_recorder`](https://github.com/leafliber/astrbot_plugin_message_recorder)

2. **安装本插件**：
   ```bash
   # 通过 AstrBot 插件市场安装
   # 或手动克隆到 plugins/ 目录
   ```

---

## 📋 命令清单

### 🎨 词云生成

| 命令 | 功能 |
|------|------|
| `今日词云` | 生成今日群聊词云 |
| `昨日词云` | 生成昨日群聊词云 |
| `本周词云` | 生成本周群聊词云 |
| `上周词云` | 生成上周群聊词云 |
| `本月词云` | 生成本月群聊词云 |
| `上月词云` | 生成上月群聊词云 |
| `年度词云` | 生成今年群聊词云 |

### 🏷️ 词性词云

| 命令 | 功能 |
|------|------|
| `词云 名词` | 生成今日名词词云（蓝色系） |
| `词云 动词` | 生成今日动词词云（绿色系） |
| `词云 形容词` | 生成今日形容词词云（橙色系） |
| `词云 副词` | 生成今日副词词云（紫色系） |

### 🏆 排名统计

| 命令 | 功能 |
|------|------|
| `今日排名` | 查看今日发言排名 |
| `本周排名` | 查看本周发言排名 |
| `本月排名` | 查看本月发言排名 |

### 📊 分析功能

| 命令 | 功能 |
|------|------|
| `今日词性分析` | 查看今日词性分布分析 |
| `本周词性分析` | 查看本周词性分布分析 |
| `本月词性分析` | 查看本月词性分布分析 |
| `今日热词` | 查看今日热词趋势（对比昨日） |
| `本周热词` | 查看本周热词趋势（对比上周） |
| `本月热词` | 查看本月热词趋势（对比上月） |
| `群聊画像` | 查看群聊语言画像（默认本月） |
| `群聊画像 本周` | 查看本周群聊语言画像 |
| `我的风格` | 查看个人语言风格（默认本月） |
| `我的风格 本周` | 查看本周个人语言风格 |

### ⚙️ 配置管理

| 命令 | 功能 |
|------|------|
| `添加词云词典 <词语> [词性]` | 添加词语到群级词典（管理员） |
| `删除词云词典 <词语>` | 从群级词典删除词语（管理员） |
| `查看词云词典` | 查看群级词典内容 |
| `设置词云形状` | 回复图片设置词云形状（管理员） |
| `删除词云形状` | 删除词云形状（管理员） |
| `开启词云每日定时发送 [时间]` | 开启每日定时发送（默认 22:00） |
| `关闭词云每日定时发送` | 关闭每日定时发送 |

---

## ⚙️ 配置说明

在 AstrBot 管理面板中可配置以下选项：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `wordcloud_pkuseg_model` | 选项 | `web` | pkuseg 分词模型（web/news/medicine/tourism） |
| `wordcloud_min_word_length` | 数字 | `2` | 词云中显示的最小词语长度 |
| `wordcloud_max_words` | 数字 | `200` | 词云中显示的最大词语数量 |
| `wordcloud_width` | 数字 | `800` | 词云图片宽度（像素） |
| `wordcloud_height` | 数字 | `600` | 词云图片高度（像素） |
| `wordcloud_background_color` | 选项 | `white` | 词云背景色（white/black/transparent） |
| `wordcloud_colormap` | 选项 | `viridis` | 词云颜色方案 |
| `wordcloud_font_file` | 文件 | - | 自定义字体文件（上传） |
| `wordcloud_stopwords_file` | 文件 | - | 自定义停用词表（上传） |
| `wordcloud_user_dict_file` | 文件 | - | 自定义用户词典（上传） |
| `wordcloud_ranking_limit` | 数字 | `10` | 排名显示的最大人数 |
| `wordcloud_ranking_show_percentage` | 开关 | `true` | 排名是否显示百分比 |
| `wordcloud_pos_noun_colormap` | 选项 | `Blues` | 名词词云颜色方案 |
| `wordcloud_pos_verb_colormap` | 选项 | `Greens` | 动词词云颜色方案 |
| `wordcloud_pos_adj_colormap` | 选项 | `Oranges` | 形容词词云颜色方案 |
| `wordcloud_pos_adv_colormap` | 选项 | `Purples` | 副词词云颜色方案 |
| `wordcloud_trend_threshold` | 数字 | `0.5` | 热词趋势变化阈值（50%） |
| `wordcloud_trend_emerging_limit` | 数字 | `10` | 新兴热词显示数量 |
| `wordcloud_trend_declining_limit` | 数字 | `5` | 衰退话题显示数量 |
| `wordcloud_profile_top_words` | 数字 | `5` | 画像高频词显示数量 |
| `wordcloud_style_adj_threshold` | 数字 | `0.15` | 形容词占比阈值（感性表达者） |
| `wordcloud_style_verb_threshold` | 数字 | `0.30` | 动词占比阈值（行动派） |
| `wordcloud_style_noun_threshold` | 数字 | `0.40` | 名词占比阈值（知识分享者） |

---

## 📖 使用示例

### 生成今日词云
```
今日词云
```

### 查看发言排名
```
今日排名
```

### 分析热词趋势
```
今日热词
```

### 查看个人风格
```
我的风格
```

### 设置定时发送
```
开启词云每日定时发送 21:30
```

---

## 🛠️ 技术栈

- **分词引擎**：spacy-pkuseg（pkuseg 的预编译版）
- **词云生成**：wordcloud
- **图像处理**：Pillow
- **矩阵运算**：numpy
- **异步请求**：aiohttp

---

## 📄 许可证

MIT License

---

<div align="center">
  <sub>Made with ❤️ by Leafiber</sub>
</div>
