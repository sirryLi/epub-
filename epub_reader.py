#!/usr/bin/env python3
"""
无边框 EPUB 阅读器 — 可隐藏在系统托盘中
支持: 无边框窗口、系统托盘、全局快捷键、透明度调节、自定义拖动、
      书签、段落缩进、阅读进度、白色背景、目录切换
"""

import sys
import os
import json
import tempfile
import zipfile
from pathlib import Path
from html import unescape

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QPushButton, QSlider, QListWidget, QSplitter, QSystemTrayIcon,
    QMenu, QAction, QFileDialog, QFrame, QSizeGrip, QScrollArea,
    QShortcut, QMessageBox,
)
from PyQt5.QtCore import (
    Qt, QPoint, QSize, QTimer, QPropertyAnimation, QEasingCurve,
    pyqtSignal, QUrl, QRect,
)
from PyQt5.QtGui import (
    QIcon, QFont, QColor, QPalette, QKeySequence, QFontDatabase,
    QCursor,
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings

import warnings
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

SETTINGS_FILE = Path.home() / ".epub_reader_settings.json"

# ── Theme (White) ─────────────────────────────────────────────
THEME = {
    "bg": "#ffffff",
    "surface": "#f5f5f5",
    "primary": "#e0e0e0",
    "accent": "#1976d2",
    "text": "#212121",
    "text_dim": "#757575",
    "border": "#e0e0e0",
    "hover": "#e8e8e8",
}


def load_settings():
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except Exception:
            pass
    return {
        "geometry": None, "opacity": 0.95, "font_size": 16,
        "last_book": None, "bookmarks": {}, "indent": 0,
        "reading_progress": {}, "toc_visible": True,
    }


def save_settings(s):
    SETTINGS_FILE.write_text(json.dumps(s, indent=2))


# ── EPUB Parser ────────────────────────────────────────────
class EpubParser:
    """解析 EPUB 文件, 提取文本/章节"""

    def __init__(self, path):
        self.book = epub.read_epub(path)
        self.path = path
        self._chapters = None

    @property
    def title(self):
        title = self.book.get_metadata("DC", "title")
        return title[0][0] if title else Path(self.path).stem

    @property
    def author(self):
        au = self.book.get_metadata("DC", "creator")
        return au[0][0] if au else "Unknown"

    @property
    def chapters(self):
        if self._chapters is None:
            self._chapters = self._parse_chapters()
        return self._chapters

    def _parse_chapters(self):
        chapters = []
        spine = self.book.spine if hasattr(self.book, "spine") else []
        id_to_href = {}
        for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            id_to_href[item.id] = item.file_name

        for idx, (item_id, _linear) in enumerate(spine):
            href = id_to_href.get(item_id, item_id)
            doc = self.book.get_item_with_href(href)
            if doc is None:
                continue
            content = doc.get_content().decode("utf-8", errors="replace")
            soup = BeautifulSoup(content, "lxml")
            title_tag = soup.find(["h1", "h2", "h3", "title"])
            title = title_tag.get_text(strip=True) if title_tag else f"Section {idx+1}"
            # Remove the heading from body so it doesn't show in the page
            if title_tag:
                title_tag.decompose()
            body = soup.find("body")
            if body:
                for img in body.find_all("img"):
                    src = img.get("src", "")
                    img_item = self._find_image(src, doc.file_name)
                    if img_item:
                        img["src"] = self._img_to_data_uri(img_item)
                html = str(body)
            else:
                html = str(soup)
            chapters.append({"title": title, "html": html, "index": idx})
        return chapters

    def _find_image(self, src, base_href):
        base_dir = os.path.dirname(base_href)
        candidates = [src, os.path.join(base_dir, src) if base_dir else src]
        for c in candidates:
            c_norm = c.replace("\\", "/")
            img = self.book.get_item_with_href(c_norm)
            if img is not None:
                return img
        return None

    def _img_to_data_uri(self, item):
        data = item.get_content()
        ext = os.path.splitext(item.file_name)[1].lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg", ".gif": "image/gif",
                    ".svg": "image/svg+xml", ".webp": "image/webp"}
        mime = mime_map.get(ext, "image/png")
        import base64
        b64 = base64.b64encode(data).decode()
        return f"data:{mime};base64,{b64}"

    def get_cover_image(self):
        try:
            cover = self.book.get_item_with_href("cover")
            if cover is None:
                for item in self.book.get_items_of_type(ebooklib.ITEM_IMAGE):
                    if "cover" in item.file_name.lower():
                        cover = item
                        break
            if cover:
                return self._img_to_data_uri(cover)
        except Exception:
            pass
        return None


# ── Custom Title Bar ───────────────────────────────────────
class TitleBar(QFrame):
    """可拖动的自定义标题栏"""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setFixedHeight(36)
        self.setStyleSheet(f"""
            QFrame {{ background: {THEME['surface']}; border-bottom: 1px solid {THEME['border']}; }}
        """)
        self.drag_pos = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 4, 0)

        self.icon_lbl = QLabel("📖")
        self.icon_lbl.setFixedWidth(24)
        layout.addWidget(self.icon_lbl)

        self.title_lbl = QLabel("EPUB Reader")
        self.title_lbl.setStyleSheet(f"color: {THEME['text_dim']}; font-size: 12px;")
        layout.addWidget(self.title_lbl)
        layout.addStretch()

        # Opacity slider
        self.opacity_lbl = QLabel("透明")
        self.opacity_lbl.setStyleSheet(f"color: {THEME['text_dim']}; font-size: 10px;")
        layout.addWidget(self.opacity_lbl)

        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setValue(int(parent.settings["opacity"] * 100))
        self.opacity_slider.setFixedWidth(80)
        self.opacity_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{ background: {THEME['primary']}; height: 4px; border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: {THEME['accent']}; width: 12px; margin: -4px 0; border-radius: 6px; }}
        """)
        self.opacity_slider.valueChanged.connect(parent.set_opacity)
        layout.addWidget(self.opacity_slider)

        for text, slot, tip in [
            ("—", parent.hide_to_tray, "隐藏到托盘"),
            ("□", parent.toggle_maximize, "最大化/还原"),
            ("✕", parent.quit_app, "退出"),
        ]:
            btn = QPushButton(text)
            btn.setFixedSize(28, 24)
            btn.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {THEME['text_dim']}; border: none; font-size: 12px; }}
                QPushButton:hover {{ background: {THEME['hover']}; color: {THEME['text']}; }}
            """)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            layout.addWidget(btn)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.drag_pos = e.globalPos() - self.parent.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self.drag_pos is not None:
            self.parent.move(e.globalPos() - self.drag_pos)

    def mouseReleaseEvent(self, e):
        self.drag_pos = None

    def mouseDoubleClickEvent(self, e):
        self.parent.toggle_maximize()


# ── Table of Contents Panel ────────────────────────────────
class TocPanel(QFrame):
    chapter_clicked = pyqtSignal(int)

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedWidth(220)
        self.setStyleSheet(f"""
            QFrame {{ background: {THEME['surface']}; border-right: 1px solid {THEME['border']}; }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        hdr = QLabel("  目录")
        hdr.setFixedHeight(32)
        hdr.setStyleSheet(f"color: {THEME['text']}; font-weight: bold; background: {THEME['primary']};")
        layout.addWidget(hdr)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{ background: transparent; border: none; color: {THEME['text_dim']}; font-size: 13px; }}
            QListWidget::item {{ padding: 6px 12px; border-bottom: 1px solid {THEME['border']}; }}
            QListWidget::item:hover {{ background: {THEME['hover']}; color: {THEME['text']}; }}
            QListWidget::item:selected {{ background: {THEME['accent']}; color: white; }}
        """)
        self.list_widget.clicked.connect(lambda idx: self.chapter_clicked.emit(idx.row()))
        layout.addWidget(self.list_widget)

    def populate(self, chapters):
        self.list_widget.clear()
        for ch in chapters:
            self.list_widget.addItem(ch["title"])


# ── Main Reader Window ─────────────────────────────────────
class EpubReader(QMainWindow):
    def __init__(self, epub_path=None):
        super().__init__()
        self.settings = load_settings()
        self.parser = None
        self.chapters = []
        self.current_chapter = 0
        self.is_maximized = False
        self.normal_geometry = None
        self._html_loaded = False

        self._setup_ui()
        self._setup_tray()
        self._setup_shortcuts()

        if epub_path:
            QTimer.singleShot(50, lambda: self.load_epub(epub_path))
        else:
            self._restore_state()

    # ── UI Setup ────────────────────────────────────────
    def _setup_ui(self):
        self.setWindowTitle("EPUB Reader")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        w, h = 1050, 720
        self.resize(w, h)

        central = QWidget()
        central.setStyleSheet(f"background: {THEME['bg']}; border-radius: 8px;")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.title_bar = TitleBar(self)
        root_layout.addWidget(self.title_bar)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet(f"QSplitter::handle {{ background: {THEME['border']}; width: 1px; }}")

        # ── TOC Panel ──
        self.toc_panel = TocPanel(self)
        self.toc_panel.chapter_clicked.connect(self.goto_chapter)
        self.splitter.addWidget(self.toc_panel)

        # ── Reading area ──
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # Chapter title bar
        self.chapter_title = QLabel("")
        self.chapter_title.setFixedHeight(30)
        self.chapter_title.setStyleSheet(f"""
            color: {THEME['text']}; font-size: 13px; font-weight: bold;
            padding: 4px 16px; background: {THEME['surface']};
            border-bottom: 1px solid {THEME['border']};
        """)
        right_layout.addWidget(self.chapter_title)

        # Web view
        self.webview = QWebEngineView()
        self.webview.setStyleSheet(f"background: {THEME['bg']};")
        settings = self.webview.settings()
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
        settings.setFontSize(QWebEngineSettings.DefaultFontSize, self.settings["font_size"])
        self.webview.loadFinished.connect(self._on_load_finished)
        right_layout.addWidget(self.webview)

        self.splitter.addWidget(right_widget)
        toc_w = 220 if self.settings.get("toc_visible", True) else 0
        self.splitter.setSizes([toc_w, w - toc_w])
        if not self.settings.get("toc_visible", True):
            self.toc_panel.hide()

        root_layout.addWidget(self.splitter)

        # ── Bottom bar ──
        bottom = QFrame()
        bottom.setFixedHeight(32)
        bottom.setStyleSheet(f"background: {THEME['surface']}; border-top: 1px solid {THEME['border']};")
        b_layout = QHBoxLayout(bottom)
        b_layout.setContentsMargins(8, 0, 8, 0)

        # Open new EPUB
        open_btn = QPushButton("📂")
        open_btn.setFixedSize(28, 24)
        open_btn.setToolTip("打开 EPUB 文件 (Ctrl+O)")
        open_btn.setStyleSheet(f"""
            QPushButton {{ color: {THEME['text_dim']}; background: transparent; border: none; font-size: 13px; }}
            QPushButton:hover {{ color: {THEME['text']}; }}
        """)
        open_btn.clicked.connect(self.open_file_dialog)
        b_layout.addWidget(open_btn)

        # TOC toggle
        self.toc_btn = QPushButton("☰")
        self.toc_btn.setFixedSize(28, 24)
        self.toc_btn.setToolTip("显示/隐藏目录")
        self.toc_btn.setStyleSheet(f"""
            QPushButton {{ color: {THEME['text_dim']}; background: transparent; border: none; font-size: 13px; }}
            QPushButton:hover {{ color: {THEME['text']}; }}
        """)
        self.toc_btn.clicked.connect(self.toggle_toc)
        b_layout.addWidget(self.toc_btn)

        # Bookmark button
        self.bkmk_btn = QPushButton("🔖")
        self.bkmk_btn.setFixedSize(28, 24)
        self.bkmk_btn.setToolTip("添加/移除书签")
        self.bkmk_btn.setStyleSheet(f"""
            QPushButton {{ color: {THEME['text_dim']}; background: transparent; border: none; font-size: 13px; }}
            QPushButton:hover {{ color: {THEME['text']}; }}
        """)
        self.bkmk_btn.clicked.connect(self.toggle_bookmark)
        b_layout.addWidget(self.bkmk_btn)

        # Bookmark list button
        self.bkmk_list_btn = QPushButton("📑")
        self.bkmk_list_btn.setFixedSize(28, 24)
        self.bkmk_list_btn.setToolTip("书签列表")
        self.bkmk_list_btn.setStyleSheet(f"""
            QPushButton {{ color: {THEME['text_dim']}; background: transparent; border: none; font-size: 13px; }}
            QPushButton:hover {{ color: {THEME['text']}; }}
        """)
        self.bkmk_list_btn.clicked.connect(self.show_bookmarks_menu)
        b_layout.addWidget(self.bkmk_list_btn)

        b_layout.addSpacing(8)

        # Indent controls
        indent_lbl = QLabel("缩进")
        indent_lbl.setStyleSheet(f"color: {THEME['text_dim']}; font-size: 11px;")
        b_layout.addWidget(indent_lbl)

        self.indent_slider = QSlider(Qt.Horizontal)
        self.indent_slider.setRange(0, 48)
        self.indent_slider.setValue(self.settings.get("indent", 0))
        self.indent_slider.setFixedWidth(60)
        self.indent_slider.setToolTip("段落缩进 (px)")
        self.indent_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{ background: {THEME['primary']}; height: 4px; border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: {THEME['accent']}; width: 10px; margin: -3px 0; border-radius: 5px; }}
        """)
        self.indent_slider.valueChanged.connect(self._on_indent_changed)
        b_layout.addWidget(self.indent_slider)

        self.indent_val_lbl = QLabel("0")
        self.indent_val_lbl.setFixedWidth(20)
        self.indent_val_lbl.setStyleSheet(f"color: {THEME['text_dim']}; font-size: 11px;")
        b_layout.addWidget(self.indent_val_lbl)

        b_layout.addStretch()

        # Chapter navigation
        self.prev_ch_btn = QPushButton("◀")
        self.prev_ch_btn.setFixedSize(24, 24)
        self.prev_ch_btn.setToolTip("上一章 (←)")
        self.prev_ch_btn.setStyleSheet(f"""
            QPushButton {{ color: {THEME['text_dim']}; background: transparent; border: none; font-size: 11px; }}
            QPushButton:hover {{ color: {THEME['accent']}; }}
        """)
        self.prev_ch_btn.clicked.connect(self.prev_chapter)
        b_layout.addWidget(self.prev_ch_btn)

        self.page_info = QLabel("")
        self.page_info.setStyleSheet(f"color: {THEME['text_dim']}; font-size: 11px;")
        self.page_info.setToolTip("点击查看章节列表")
        self.page_info.mousePressEvent = lambda e: self._show_chapter_menu()
        b_layout.addWidget(self.page_info)

        self.next_ch_btn = QPushButton("▶")
        self.next_ch_btn.setFixedSize(24, 24)
        self.next_ch_btn.setToolTip("下一章 (→)")
        self.next_ch_btn.setStyleSheet(f"""
            QPushButton {{ color: {THEME['text_dim']}; background: transparent; border: none; font-size: 11px; }}
            QPushButton:hover {{ color: {THEME['accent']}; }}
        """)
        self.next_ch_btn.clicked.connect(self.next_chapter)
        b_layout.addWidget(self.next_ch_btn)

        b_layout.addStretch()

        # Font size controls
        for lbl, delta in [("A⁻", -1), ("A⁺", +1)]:
            btn = QPushButton(lbl)
            btn.setFixedSize(28, 24)
            btn.setStyleSheet(f"""
                QPushButton {{ color: {THEME['text_dim']}; background: transparent; border: none; font-size: 11px; }}
                QPushButton:hover {{ color: {THEME['text']}; }}
            """)
            btn.clicked.connect(lambda _, d=delta: self.change_font_size(d))
            b_layout.addWidget(btn)

        root_layout.addWidget(bottom)

        # Four QSizeGrips in corners
        self._grips = []
        for _ in range(4):
            g = QSizeGrip(self)
            g.setFixedSize(16, 16)
            g.setStyleSheet("background: transparent;")
            self._grips.append(g)

        self.set_opacity(self.settings["opacity"])

    # ── WebView load finished ────────────────────────────
    def _on_load_finished(self, ok):
        if not ok:
            return
        self._html_loaded = True
        # Restore scroll position for this chapter
        book_path = self.settings.get("last_book", "")
        progress = self.settings.get("reading_progress", {})
        if book_path in progress:
            ch_key = str(self.current_chapter)
            if ch_key in progress[book_path]:
                scroll_pct = progress[book_path][ch_key]
                if scroll_pct is not None:
                    self.webview.page().runJavaScript(
                        f"if(document.body) window.scrollTo(0, document.body.scrollHeight * {scroll_pct / 100});"
                    )

    # ── Save scroll position ─────────────────────────────
    def _save_scroll_position(self):
        if not self._html_loaded:
            return
        book_path = self.settings.get("last_book", "")
        if not book_path:
            return
        self.webview.page().runJavaScript(
            "document.body ? Math.round(window.scrollY / document.body.scrollHeight * 100) || 0 : 0",
            lambda val: self._store_scroll_progress(val)
        )

    def _store_scroll_progress(self, pct):
        if pct is None:
            return
        book_path = self.settings.get("last_book", "")
        if not book_path:
            return
        progress = self.settings.get("reading_progress", {})
        if book_path not in progress:
            progress[book_path] = {}
        progress[book_path][str(self.current_chapter)] = pct
        self.settings["reading_progress"] = progress
        save_settings(self.settings)

    # ── System Tray ────────────────────────────────────
    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        pixmap = self._make_tray_icon()
        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip("EPUB Reader")

        tray_menu = QMenu()
        show_action = QAction("显示", self)
        show_action.triggered.connect(self.show_from_tray)
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()

        open_action = QAction("打开 EPUB...", self)
        open_action.triggered.connect(self.open_file_dialog)
        tray_menu.addAction(open_action)
        tray_menu.addSeparator()

        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._tray_activated)
        self.tray_icon.show()

    def _make_tray_icon(self):
        from PyQt5.QtGui import QPainter, QPixmap, QPen, QBrush
        pm = QPixmap(32, 32)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor(THEME["accent"])))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(4, 2, 24, 28, 4, 4)
        p.setBrush(QBrush(QColor("white")))
        p.drawRect(8, 8, 16, 2)
        p.drawRect(8, 13, 12, 2)
        p.drawRect(8, 18, 14, 2)
        p.end()
        return pm

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_from_tray()

    # ── Shortcuts ──────────────────────────────────────
    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Esc"), self, self.hide_to_tray)
        QShortcut(QKeySequence("Ctrl+H"), self, self.hide_to_tray)
        QShortcut(QKeySequence("Ctrl+O"), self, self.open_file_dialog)
        QShortcut(QKeySequence("Ctrl+Q"), self, self.quit_app)
        QShortcut(QKeySequence("Ctrl+F"), self, self.toggle_fullscreen)
        QShortcut(QKeySequence("Ctrl+B"), self, self.toggle_bookmark)
        QShortcut(QKeySequence("Ctrl+D"), self, self.toggle_toc)
        QShortcut(QKeySequence("Right"), self, self.next_chapter)
        QShortcut(QKeySequence("Left"), self, self.prev_chapter)
        QShortcut(QKeySequence("Ctrl++"), self, lambda: self.change_font_size(1))
        QShortcut(QKeySequence("Ctrl+-"), self, lambda: self.change_font_size(-1))

    # ── State ──────────────────────────────────────────
    def _restore_state(self):
        geo = self.settings.get("geometry")
        if geo and len(geo) == 4:
            try:
                screen = QApplication.desktop().availableGeometry(self)
                w, h = geo[2], geo[3]
                if w <= screen.width() and h <= screen.height():
                    self.setGeometry(*geo)
            except Exception:
                pass
        last = self.settings.get("last_book")
        if last and os.path.exists(last):
            self.load_epub(last)

    def _save_state(self):
        self.settings["geometry"] = [self.x(), self.y(), self.width(), self.height()]
        self.settings["font_size"] = self.webview.settings().fontSize(
            QWebEngineSettings.DefaultFontSize
        )
        self._save_scroll_position()
        save_settings(self.settings)

    # ── EPUB Operations ────────────────────────────────
    def open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 EPUB 文件", "",
            "EPUB Files (*.epub);;All Files (*)"
        )
        if path:
            self.load_epub(path)

    def load_epub(self, path):
        try:
            self.parser = EpubParser(path)
            self.chapters = self.parser.chapters
            if not self.chapters:
                QMessageBox.warning(self, "警告", "未能解析到任何章节内容。")
                return

            self.settings["last_book"] = path
            save_settings(self.settings)

            self.title_bar.title_lbl.setText(f"{self.parser.title} — {self.parser.author}")

            # Mark bookmarked chapters in TOC
            self._update_toc_display()

            # Determine which chapter to open: restore progress or start from 0
            progress = self.settings.get("reading_progress", {})
            start_ch = 0
            if path in progress:
                # Find the last read chapter (highest chapter index with progress > 0)
                best_ch = 0
                best_pct = 0
                for ch_key, pct in progress[path].items():
                    if pct is None:
                        continue
                    ch_idx = int(ch_key)
                    if ch_idx >= best_ch and pct > best_pct:
                        best_ch = ch_idx
                        best_pct = pct
                if best_pct > 0:
                    start_ch = best_ch

            self.goto_chapter(start_ch)
            self.show()
            self.raise_()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开 EPUB 文件:\n{e}")

    def goto_chapter(self, idx):
        if 0 <= idx < len(self.chapters):
            # Save scroll position of current chapter before switching
            self._save_scroll_position()
            self.current_chapter = idx
            ch = self.chapters[idx]
            self.chapter_title.setText(f"  {ch['title']}")
            html = self._wrap_html(ch["html"])
            self.webview.setHtml(html, QUrl("about:blank"))
            self.toc_panel.list_widget.setCurrentRow(idx)
            # Show bookmark status in book info
            book_path = self.settings.get("last_book", "")
            bookmarks = self.settings.get("bookmarks", {})
            bkmk_chapters = bookmarks.get(book_path, [])
            bkmk_indicator = "  🔖" if idx in bkmk_chapters else ""
            self.page_info.setText(f"章节 {idx+1} / {len(self.chapters)}{bkmk_indicator}")
            self._save_state()

    def next_chapter(self):
        if self.current_chapter < len(self.chapters) - 1:
            self.goto_chapter(self.current_chapter + 1)

    def prev_chapter(self):
        if self.current_chapter > 0:
            self.goto_chapter(self.current_chapter - 1)

    def _show_chapter_menu(self):
        if not self.chapters:
            return
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: {THEME['bg']}; border: 1px solid {THEME['border']}; padding: 4px; }}
            QMenu::item {{ padding: 4px 20px; color: {THEME['text']}; }}
            QMenu::item:selected {{ background: {THEME['accent']}; color: white; }}
        """)
        for i, ch in enumerate(self.chapters):
            title = ch['title'][:50] + ('...' if len(ch['title']) > 50 else '')
            prefix = "● " if i == self.current_chapter else "  "
            action = menu.addAction(f"{prefix}{i+1}. {title}")
            action.triggered.connect(lambda _, idx=i: self.goto_chapter(idx))
        menu.exec_(self.page_info.mapToGlobal(self.page_info.rect().bottomLeft()))

    def _wrap_html(self, body_html):
        fs = self.webview.settings().fontSize(QWebEngineSettings.DefaultFontSize)
        indent = self.settings.get("indent", 0)
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{
      font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
      font-size: {fs}px;
      line-height: 1.8;
      color: {THEME['text']};
      background: {THEME['bg']};
      max-width: 720px;
      margin: 24px auto;
      padding: 0 20px;
  }}
  p {{ margin: 0.8em 0; text-indent: {indent}px; }}
  h1, h2, h3 {{ color: {THEME['accent']}; margin-top: 1.5em; }}
  img {{ max-width: 100%%; height: auto; border-radius: 4px; }}
  a {{ color: {THEME['accent']}; }}
  blockquote {{
      border-left: 3px solid {THEME['accent']};
      padding-left: 16px;
      color: {THEME['text_dim']};
      margin: 1em 0;
  }}
  code {{ background: {THEME['surface']}; padding: 2px 6px; border-radius: 3px; }}
  pre {{ background: {THEME['surface']}; padding: 12px; border-radius: 6px; overflow-x: auto; }}
  ::-webkit-scrollbar {{ width: 6px; }}
  ::-webkit-scrollbar-track {{ background: {THEME['bg']}; }}
  ::-webkit-scrollbar-thumb {{ background: {THEME['border']}; border-radius: 3px; }}
</style></head>
<body>{body_html}</body></html>"""

    # ── TOC Toggle ─────────────────────────────────────
    def toggle_toc(self):
        visible = not self.toc_panel.isVisible()
        self.toc_panel.setVisible(visible)
        if visible:
            total = sum(self.splitter.sizes())
            self.splitter.setSizes([220, total - 220])
        self.settings["toc_visible"] = visible
        save_settings(self.settings)

    # ── Bookmark Operations ─────────────────────────────
    def toggle_bookmark(self):
        book_path = self.settings.get("last_book", "")
        if not book_path:
            return
        bookmarks = self.settings.get("bookmarks", {})
        if book_path not in bookmarks:
            bookmarks[book_path] = []
        b_list = bookmarks[book_path]
        ch = self.current_chapter
        if ch in b_list:
            b_list.remove(ch)
            self.tray_icon.showMessage("书签", "已移除书签", QSystemTrayIcon.Information, 1000)
        else:
            b_list.append(ch)
            b_list.sort()
            self.tray_icon.showMessage("书签", f"已添加书签: {self.chapters[ch]['title']}",
                                       QSystemTrayIcon.Information, 1000)
        bookmarks[book_path] = b_list
        self.settings["bookmarks"] = bookmarks
        save_settings(self.settings)
        self._update_toc_display()
        # Update page info indicator
        bkmk_indicator = "  🔖" if ch in b_list else ""
        self.page_info.setText(f"章节 {ch+1} / {len(self.chapters)}{bkmk_indicator}")

    def show_bookmarks_menu(self):
        book_path = self.settings.get("last_book", "")
        bookmarks = self.settings.get("bookmarks", {})
        b_list = bookmarks.get(book_path, [])

        if not b_list:
            QMessageBox.information(self, "书签", "当前书籍没有书签。\n按 Ctrl+B 或点击 🔖 添加书签。")
            return

        menu = QMenu(self)
        for ch_idx in b_list:
            if 0 <= ch_idx < len(self.chapters):
                title = self.chapters[ch_idx]["title"]
                action = QAction(f"{ch_idx+1}. {title}", self)
                action.triggered.connect(lambda _, i=ch_idx: self.goto_chapter(i))
                menu.addAction(action)
        menu.exec_(self.bkmk_list_btn.mapToGlobal(QPoint(0, self.bkmk_list_btn.height())))

    def _update_toc_display(self):
        """Update TOC to show bookmark indicators"""
        self.toc_panel.populate(self.chapters)
        book_path = self.settings.get("last_book", "")
        bookmarks = self.settings.get("bookmarks", {})
        b_list = bookmarks.get(book_path, [])
        for i in range(self.toc_panel.list_widget.count()):
            item = self.toc_panel.list_widget.item(i)
            if i in b_list:
                item.setText(f"🔖 {item.text()}")
        # Restore selection
        self.toc_panel.list_widget.setCurrentRow(self.current_chapter)

    # ── Indentation ────────────────────────────────────
    def _on_indent_changed(self, value):
        self.settings["indent"] = value
        self.indent_val_lbl.setText(str(value))
        if self.chapters:
            self.goto_chapter(self.current_chapter)

    # ── Window Controls ────────────────────────────────
    def hide_to_tray(self):
        self._save_scroll_position()
        self.normal_geometry = self.geometry()
        self.hide()
        self.tray_icon.showMessage("EPUB Reader", "已隐藏到系统托盘。\n双击托盘图标或按 Ctrl+H 显示。",
                                   QSystemTrayIcon.Information, 2000)

    def show_from_tray(self):
        if self.normal_geometry:
            self.setGeometry(self.normal_geometry)
        self.show()
        self.raise_()
        self.activateWindow()

    def toggle_maximize(self):
        if self.is_maximized:
            if self.normal_geometry:
                self.setGeometry(self.normal_geometry)
            self.is_maximized = False
        else:
            self.normal_geometry = self.geometry()
            self.showMaximized()
            self.is_maximized = True

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def set_opacity(self, value):
        opacity = max(0.3, value / 100.0)
        self.setWindowOpacity(opacity)
        self.settings["opacity"] = opacity

    def change_font_size(self, delta):
        s = self.webview.settings()
        current = s.fontSize(QWebEngineSettings.DefaultFontSize)
        new_size = max(10, min(28, current + delta))
        s.setFontSize(QWebEngineSettings.DefaultFontSize, new_size)
        self.settings["font_size"] = new_size
        if self.chapters:
            self.goto_chapter(self.current_chapter)

    def quit_app(self):
        self._save_scroll_position()
        self._save_state()
        self.tray_icon.hide()
        QApplication.quit()

    # ── Events ─────────────────────────────────────────
    def closeEvent(self, event):
        event.ignore()
        self.hide_to_tray()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._save_state()
        # Position QSizeGrips at corners
        w, h = self.width(), self.height()
        s = 16
        self._grips[0].move(0, 0)                     # top-left
        self._grips[1].move(w - s, 0)                  # top-right
        self._grips[2].move(0, h - s)                  # bottom-left
        self._grips[3].move(w - s, h - s)              # bottom-right

    def moveEvent(self, event):
        super().moveEvent(event)
        self._save_state()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".epub"):
                self.load_epub(path)
                break


# ── Entry Point ────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("EPUB Reader")
    app.setQuitOnLastWindowClosed(False)

    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(THEME["bg"]))
    palette.setColor(QPalette.WindowText, QColor(THEME["text"]))
    app.setPalette(palette)

    epub_path = sys.argv[1] if len(sys.argv) > 1 else None
    reader = EpubReader(epub_path=epub_path)
    reader.show()

    if not reader.chapters:
        QTimer.singleShot(300, reader.open_file_dialog)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
