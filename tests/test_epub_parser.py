"""非 GUI 单元测试 — EPUB 解析器 + 设置持久化"""

import json
from pathlib import Path

from epub_reader import EpubParser, load_settings, save_settings, SETTINGS_FILE


def test_parse_title(test_epub_path):
    parser = EpubParser(test_epub_path)
    assert parser.title == "测试电子书"


def test_parse_author(test_epub_path):
    parser = EpubParser(test_epub_path)
    assert parser.author == "测试作者"


def test_parse_chapter_count(test_epub_path):
    parser = EpubParser(test_epub_path)
    assert len(parser.chapters) == 3


def test_parse_chapter_titles(test_epub_path):
    parser = EpubParser(test_epub_path)
    titles = [ch["title"] for ch in parser.chapters]
    assert titles == ["第1章 测试章节", "第2章 测试章节", "第3章 测试章节"]


def test_chapter_html_not_empty(test_epub_path):
    parser = EpubParser(test_epub_path)
    for ch in parser.chapters:
        assert "<h1>" in ch["html"]
        assert len(ch["html"]) > 100


def test_chapter_index_field(test_epub_path):
    parser = EpubParser(test_epub_path)
    for i, ch in enumerate(parser.chapters):
        assert ch["index"] == i


def test_empty_spine(empty_epub_path):
    parser = EpubParser(empty_epub_path)
    assert parser.chapters == []


def test_settings_roundtrip(tmp_path, monkeypatch):
    test_file = tmp_path / "settings.json"
    monkeypatch.setattr("epub_reader.SETTINGS_FILE", test_file)

    s = {"geometry": [100, 200, 800, 600], "opacity": 0.8, "font_size": 16}
    save_settings(s)

    loaded = load_settings()
    assert loaded == s


def test_load_settings_default(monkeypatch):
    """SETTINGS_FILE 不存在时返回默认值"""
    monkeypatch.setattr("epub_reader.SETTINGS_FILE", Path("/nonexistent/settings.json"))
    s = load_settings()
    assert s == {"geometry": None, "opacity": 0.95, "font_size": 16, "last_book": None}


def test_load_settings_corrupt(tmp_path, monkeypatch):
    """设置文件损坏时返回默认值"""
    bad = tmp_path / "bad.json"
    bad.write_text("not valid json {{{")
    monkeypatch.setattr("epub_reader.SETTINGS_FILE", bad)
    s = load_settings()
    assert s == {"geometry": None, "opacity": 0.95, "font_size": 16, "last_book": None}
