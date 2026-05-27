# 🎌 番剧自动订阅管理

每季度初从 yuc.wiki 抓取当季番单 → 蜜柑计划搜索 RSS → 按字幕组优先级（ANi > kirara > 其他）
自动添加到本地 qBittorrent，每两个季度清理旧资源。

## 快速开始

### 1. 安装依赖

```bash
uv sync
uv run scrapling install   # 首次安装浏览器驱动
```

### 2. 配置 qBittorrent

编辑 config.yaml，填入 WebUI 账号密码（端口默认 8080）。

### 3. 启动

```bash
uv run streamlit run app.py
```

## 使用流程

- 首次：⚙️ 设置 → 测试连接
- 每季初：📺 季度订阅 → 从 yuc.wiki 加载 → 勾选 → 订阅
- 日常：📋 订阅管理
- 每半年：🗑️ 季度清理

## 运行测试

```bash
uv run pytest tests/ -v
```
