"""GUI 集成测试 — 使用 pytest-qt 验证完整交互流程"""

import pytest
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon
from PyQt5.QtWebEngineWidgets import QWebEngineView

from epub_reader import EpubReader


@pytest.fixture
def reader(qtbot, test_epub_path):
    """创建已加载 EPUB 的阅读器实例"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    app.setQuitOnLastWindowClosed(False)

    r = EpubReader(epub_path=test_epub_path)
    qtbot.addWidget(r)

    # 等待 QTimer 触发 load_epub + webview 加载完成
    _wait_loaded(qtbot, r)

    yield r

    r.tray_icon.hide()
    r.close()
    # 强制清理，避免残留状态影响后续测试
    if r.isVisible():
        r.hide()


def _wait_loaded(qtbot, r, timeout=5000):
    """等待 EPUB 加载 + webview 渲染完成"""

    def loaded():
        return len(r.chapters) > 0 and r.webview.isVisible()

    qtbot.waitUntil(loaded, timeout=timeout)

    # 再等 webview loadFinished
    if r.chapters:
        qtbot.waitSignal(r.webview.loadFinished, timeout=timeout)


# ── 窗口创建 ──────────────────────────────────────────────

def test_window_visible_after_creation(reader):
    assert reader.isVisible()
    assert reader.windowTitle() == "EPUB Reader"


def test_chapters_loaded(reader):
    assert len(reader.chapters) == 3
    assert reader.toc_panel.list_widget.count() == 3


def test_chapter_title_displayed(reader):
    assert "第1章" in reader.chapter_title.text()


# ── 章节导航 ──────────────────────────────────────────────

def test_chapter_navigation_next(qtbot, reader):
    reader.next_chapter()
    qtbot.waitSignal(reader.webview.loadFinished, timeout=5000)
    assert reader.current_chapter == 1
    assert "第2章" in reader.chapter_title.text()


def test_chapter_navigation_prev(qtbot, reader):
    reader.goto_chapter(2)
    qtbot.waitSignal(reader.webview.loadFinished, timeout=5000)
    reader.prev_chapter()
    qtbot.waitSignal(reader.webview.loadFinished, timeout=5000)
    assert reader.current_chapter == 1
    assert "第2章" in reader.chapter_title.text()


def test_goto_chapter(qtbot, reader):
    reader.goto_chapter(2)
    qtbot.waitSignal(reader.webview.loadFinished, timeout=5000)
    assert reader.current_chapter == 2
    assert "第3章" in reader.chapter_title.text()


def test_next_chapter_at_end_stays(qtbot, reader):
    reader.goto_chapter(2)
    qtbot.waitSignal(reader.webview.loadFinished, timeout=5000)
    reader.next_chapter()
    assert reader.current_chapter == 2  # 未越界


def test_prev_chapter_at_start_stays(qtbot, reader):
    reader.prev_chapter()
    assert reader.current_chapter == 0  # 未越界


def test_toc_click_triggers_navigation(qtbot, reader):
    # 模拟点击目录第二项
    reader.toc_panel.list_widget.setCurrentRow(1)
    reader.toc_panel.chapter_clicked.emit(1)
    qtbot.waitSignal(reader.webview.loadFinished, timeout=5000)
    assert reader.current_chapter == 1


# ── 字体缩放 ──────────────────────────────────────────────

def test_change_font_size_increase(qtbot, reader):
    from PyQt5.QtWebEngineWidgets import QWebEngineSettings

    s = reader.webview.settings()
    original = s.fontSize(QWebEngineSettings.DefaultFontSize)
    reader.change_font_size(3)
    qtbot.waitSignal(reader.webview.loadFinished, timeout=5000)
    new_size = s.fontSize(QWebEngineSettings.DefaultFontSize)
    assert new_size == original + 3


def test_change_font_size_decrease(qtbot, reader):
    from PyQt5.QtWebEngineWidgets import QWebEngineSettings

    s = reader.webview.settings()
    reader.change_font_size(5)
    qtbot.waitSignal(reader.webview.loadFinished, timeout=5000)
    mid = s.fontSize(QWebEngineSettings.DefaultFontSize)

    reader.change_font_size(-2)
    qtbot.waitSignal(reader.webview.loadFinished, timeout=5000)
    assert s.fontSize(QWebEngineSettings.DefaultFontSize) == mid - 2


def test_change_font_size_clamped_low(qtbot, reader):
    from PyQt5.QtWebEngineWidgets import QWebEngineSettings

    s = reader.webview.settings()
    # 试图降到 0 以下
    reader.change_font_size(-100)
    qtbot.waitSignal(reader.webview.loadFinished, timeout=5000)
    assert s.fontSize(QWebEngineSettings.DefaultFontSize) >= 10


def test_change_font_size_clamped_high(qtbot, reader):
    from PyQt5.QtWebEngineWidgets import QWebEngineSettings

    s = reader.webview.settings()
    reader.change_font_size(100)
    qtbot.waitSignal(reader.webview.loadFinished, timeout=5000)
    assert s.fontSize(QWebEngineSettings.DefaultFontSize) <= 28


# ── 透明度 ────────────────────────────────────────────────

def test_opacity_set():
    app = QApplication.instance()
    r = EpubReader()
    r.set_opacity(50)
    assert 0.49 < r.windowOpacity() < 0.51
    r.tray_icon.hide()
    r.hide()


def test_opacity_clamped():
    app = QApplication.instance()
    r = EpubReader()
    r.set_opacity(10)
    assert r.windowOpacity() >= 0.3
    r.tray_icon.hide()
    r.hide()


# ── 托盘隐藏/恢复 ─────────────────────────────────────────

def test_hide_to_tray(reader):
    reader.hide_to_tray()
    assert not reader.isVisible()
    assert reader.tray_icon.isVisible()


def test_show_from_tray(reader):
    reader.hide_to_tray()
    reader.show_from_tray()
    assert reader.isVisible()


# ── 页面信息 ──────────────────────────────────────────────

def test_page_info_updated(qtbot, reader):
    assert "1 / 3" in reader.page_info.text()
    reader.goto_chapter(2)
    qtbot.waitSignal(reader.webview.loadFinished, timeout=5000)
    assert "3 / 3" in reader.page_info.text()


# ── 设置保存 ──────────────────────────────────────────────

def test_settings_saved_after_navigation(qtbot, reader):
    reader.goto_chapter(1)
    qtbot.waitSignal(reader.webview.loadFinished, timeout=5000)
    s = reader.settings
    assert s["last_book"] is not None
    assert "geometry" in s
