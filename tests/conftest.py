"""共享 fixtures"""

import pytest
from tests.epub_generator import create_test_epub, create_empty_epub


@pytest.fixture(scope="session")
def test_epub_path():
    """生成一个 3 章节的测试 EPUB，整个 session 复用"""
    path = create_test_epub(chapter_count=3)
    yield path
    # cleanup 由 OS 处理临时文件


@pytest.fixture(scope="session")
def empty_epub_path():
    """生成一个无章节的空白 EPUB"""
    path = create_empty_epub()
    yield path
