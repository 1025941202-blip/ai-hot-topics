# AI 爆款选题库自动化（MVP）

本项目提供一个本地运行的自动化流水线，用于抓取 AI 相关热点内容，生成候选选题、评分和短视频口播提纲，并同步到飞书多维表格（可选）。

## 快速开始

1. 创建环境并安装：

```bash
cd /Users/jiejie/Desktop/LVYU/projects/AI热点
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

2. 配置环境变量：

```bash
cp .env.example .env
```

浏览器平台（抖音/小红书/X/灰豚）需要设置 `PLAYWRIGHT_USER_DATA_DIR`，并使用该目录登录一次浏览器以保留登录态。

可用登录初始化脚本（会打开浏览器并等待你登录后按 Enter 关闭）：

```bash
/Users/jiejie/Desktop/LVYU/projects/AI热点/.venv/bin/python \
  /Users/jiejie/Desktop/LVYU/projects/AI热点/scripts/browser_login_bootstrap.py \
  --project-dir /Users/jiejie/Desktop/LVYU/projects/AI热点 \
  --platform all
```

3. 运行全流程（默认使用 mock LLM，未配置平台凭据时会自动降级并记录日志）：

```bash
python3 -m ai_hot_topics.cli run-daily --project-dir /Users/jiejie/Desktop/LVYU/projects/AI热点
```

灰豚数据单独采集（真实后台接口 `dyapi.huitun.com/user/webHomePage`）：

```bash
PYTHONPATH=/Users/jiejie/Desktop/LVYU/projects/AI热点/src \
/Users/jiejie/Desktop/LVYU/projects/AI热点/.venv/bin/python -m ai_hot_topics.cli \
  --project-dir /Users/jiejie/Desktop/LVYU/projects/AI热点 \
  collect --platform huitun --since-hours 48 --max-per-keyword 20
```

4. 运行测试：

```bash
python3 -m unittest discover -s /Users/jiejie/Desktop/LVYU/projects/AI热点/tests -p 'test_*.py'
```

## 可视化看板（推荐）

启动本地网页看板（默认聚焦小红书）：

```bash
PYTHONPATH=/Users/jiejie/Desktop/LVYU/projects/AI热点/src \
/Users/jiejie/Desktop/LVYU/projects/AI热点/.venv/bin/python -m ai_hot_topics.cli \
  --project-dir /Users/jiejie/Desktop/LVYU/projects/AI热点 \
  dashboard --host 127.0.0.1 --port 8765 --open
```

打开后可用功能：
- 查看候选选题列表、互动指标（阅读/点赞/收藏/评论/分享）、博主信息、来源链接
- 按关键词、分数、审核状态筛选
- 支持按 `点赞/收藏/评论` 排序（升序/降序）
- 在页面内把候选状态改为 `待处理 / 已通过 / 已拒绝`

## 团队共享访问

如果同一局域网内要给团队成员访问，把 host 改为 `0.0.0.0`：

```bash
PYTHONPATH=/Users/jiejie/Desktop/LVYU/projects/AI热点/src \
/Users/jiejie/Desktop/LVYU/projects/AI热点/.venv/bin/python -m ai_hot_topics.cli \
  --project-dir /Users/jiejie/Desktop/LVYU/projects/AI热点 \
  dashboard --host 0.0.0.0 --port 8765
```

然后把你电脑局域网地址发给同事，例如：
- `http://192.168.31.88:8765`

## GitHub Pages 公开网址

如果你要给学员一个“直接打开的网址”，可以使用仓库的 `GitHub Pages`（静态页面）：

1. 先导出最新候选数据到 `docs/data/candidates.json`

```bash
cd /Users/jiejie/Desktop/LVYU/projects/AI热点
PYTHONPATH=src ./.venv/bin/python scripts/export_pages_data.py \
  --project-dir /Users/jiejie/Desktop/LVYU/projects/AI热点 \
  --output /Users/jiejie/Desktop/LVYU/projects/AI热点/docs/data/candidates.json \
  --limit 300 --sort-by likes --sort-order desc
```

2. 提交并推送 `docs/` 目录后，Pages 网址可直接访问。

说明：
- Pages 是静态快照，不会自动实时抓取灰豚；
- 你每次跑完采集后重新执行一次导出并推送，网页就会更新。

### 自动推送（免手动）

项目已提供自动发布脚本：
- `/Users/jiejie/Desktop/LVYU/projects/AI热点/scripts/publish_pages_snapshot.sh`

该脚本会自动执行：
- 抓取平台（默认 `xiaohongshu,huitun`）
- `process` 聚类评分
- 导出 `docs/data/candidates.json`
- `git commit` + `git push`

安装每日定时自动发布（默认每天 09:20）：

```bash
bash /Users/jiejie/Desktop/LVYU/projects/AI热点/scripts/install_pages_publish_launchd.sh \
  /Users/jiejie/Desktop/LVYU/projects/AI热点 \
  /Users/jiejie/Desktop/LVYU/projects/AI热点/.venv/bin/python \
  9 20
```

手动触发一次（用于验证）：

```bash
bash /Users/jiejie/Desktop/LVYU/projects/AI热点/scripts/publish_pages_snapshot.sh \
  /Users/jiejie/Desktop/LVYU/projects/AI热点 \
  /Users/jiejie/Desktop/LVYU/projects/AI热点/.venv/bin/python
```

日志路径：
- `/Users/jiejie/Desktop/LVYU/projects/AI热点/data/logs/pages-publish.out.log`
- `/Users/jiejie/Desktop/LVYU/projects/AI热点/data/logs/pages-publish.err.log`
