# EPUB Reader

无边框桌面 EPUB 阅读器，支持系统托盘隐藏、阅读进度保存、书签、段落缩进调节等功能。

## 功能

- **无边框窗口** — 简洁白色界面，四角可拖拽缩放，标题栏可拖动
- **系统托盘** — 关闭窗口自动隐藏到托盘，双击托盘图标恢复
- **目录面板** — 左侧目录树，点击快速跳转章节
- **章节导航** — 底部 ◀ ▶ 按钮、← → 方向键、点击章节号弹出跳转列表
- **阅读进度** — 自动保存每本书每个章节的滚动位置，下次打开自动恢复
- **书签** — Ctrl+B 添加/移除书签，📑 查看书签列表
- **段落缩进** — 底部滑块调节 0-48px
- **字体大小** — A⁻ / A⁺ 按钮或 Ctrl+/- 调节
- **窗口透明度** — 标题栏滑块调节
- **拖放打开** — 拖拽 .epub 文件到窗口打开
- **命令行打开** — `epub_reader.exe book.epub`

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| Esc / Ctrl+H | 隐藏到系统托盘 |
| Ctrl+O | 打开 EPUB 文件 |
| Ctrl+B | 添加/移除书签 |
| Ctrl+D | 显示/隐藏目录 |
| Ctrl+F | 全屏切换 |
| ← → | 上一章 / 下一章 |
| Ctrl+/- | 增大/减小字体 |
| Ctrl+Q | 退出程序 |

## 安装与运行

```bash
pip install PyQt5 PyQtWebEngine ebooklib beautifulsoup4 lxml
python epub_reader.py
```

## 打包为 exe

```bash
pip install pyinstaller
rmdir /s /q build dist
pyinstaller epub_reader.spec
```

打包后 `dist/epub_reader/` 即为可分发的程序目录。

## 数据存储

所有设置和阅读进度保存在 `~/.epub_reader_settings.json`，包括：

- 窗口位置/大小
- 打开过的书籍及阅读进度
- 书签
- 字体大小、缩进、透明度等偏好
