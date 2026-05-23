# AI Weekly

自动化的每周 AI 资讯 Top 10 生成器。从 Hacker News、Reddit、RSS、ArXiv 等主流技术源收集本周最热门的 AI 新闻，通过三种评分算法生成三份独立的 Top 10 榜单，并用 DeepSeek 生成中文摘要。

## 工作流程

```
每周一 9:00 CST (定时) / 手动触发
         │
         ▼
  ┌──────────────┐
  │ 1. Collect    │  HN / Reddit / RSS / ArXiv / GNews
  ├──────────────┤
  │ 2. Rank       │  3 种算法 × 3 份 Top 10
  ├──────────────┤
  │ 3. Summarize  │  DeepSeek 中文摘要 + 图片提示词
  ├──────────────┤
  │ 4. Images     │  可选 (默认关闭)
  ├──────────────┤
  │ 5. Compose    │  Markdown 新闻稿 + 小红书文案
  └──────────────┘
         │
         ▼
  创建 PR → 人工审核 → Merge → 自动 Tag 归档
```

## 三种评分算法

| 算法 | 偏好 | 适用场景 |
|------|------|----------|
| **热度优先** | 社区参与度 (投票/评论) | 大家都在聊什么 |
| **影响力优先** | 来源权威性 + 技术信号 | 什么改变了 AI 格局 |
| **新鲜度优先** | 时效性 + 新颖度 | 本周最新动态 |

每周生成三份榜单，从 [comparison.md](output/) 快速对比选出最佳版本。

## 数据源

- Hacker News (Firebase API)
- Reddit (r/MachineLearning, r/artificial, r/singularity)
- TechCrunch / VentureBeat / The Verge (RSS)
- ArXiv (cs.AI, cs.LG, cs.CL)
- GNews

## 快速开始

### 本地运行

```bash
pip install -r requirements.txt

# 设置环境变量
export DEEPSEEK_API_KEY=sk-xxx

# 预览模式 (采集 + 排序 + 摘要，不生成文件)
python -m ai_weekly.main --dry-run

# 完整运行
python -m ai_weekly.main --run --output-dir output/$(date +%Y-%m-%d)
```

### GitHub Actions

1. Fork 此仓库
2. 在 Settings → Secrets 中添加 `DEEPSEEK_API_KEY`
3. 在 Settings → Actions → General 中启用 "Allow GitHub Actions to create pull requests"
4. 手动触发: Actions → Generate Weekly Content → Run workflow
5. 定时任务: 每周一 9:00 CST 自动运行

## 配置

编辑 `config.yaml` 可以调整:
- 数据源开关和参数
- 三种算法的评分权重
- LLM 和图片生成设置
- 代理设置 (本地调试用)

## 项目结构

```
├── .github/workflows/
│   ├── generate.yml       # 内容生成 + 自动 PR
│   └── archive.yml        # Merge 时自动 Tag
├── ai_weekly/
│   ├── main.py            # Pipeline 编排
│   ├── config.py          # 配置加载
│   ├── db.py              # SQLite 数据层
│   ├── ranker.py          # 三算法排序
│   ├── summarizer.py      # DeepSeek 摘要
│   ├── image_gen.py       # 配图生成
│   ├── composer.py        # 新闻稿合成
│   └── collector/
│       ├── hackernews.py
│       ├── reddit.py
│       ├── rss.py
│       ├── arxiv.py
│       └── newsapi.py
├── config.yaml            # 配置文件
└── output/                # 生成内容 (Git 追踪)
```

## License

MIT
