"""程序化生成用于测试的迷你 EPUB 文件"""

import io
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw

from ebooklib import epub


def _make_cover_image() -> bytes:
    """生成一个 200x300 的纯色封面 PNG"""
    img = Image.new("RGB", (200, 300), color=(25, 26, 46))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 120, 160, 180], fill=(233, 69, 96))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def create_test_epub(chapter_count=3) -> str:
    """生成一个包含中文章节的测试 EPUB，返回文件路径"""
    book = epub.EpubBook()
    book.set_identifier("test-epub-001")
    book.set_title("测试电子书")
    book.set_language("zh")
    book.add_author("测试作者")

    # 封面图片
    book.set_cover("cover.png", _make_cover_image())

    # 章节
    chapters = []
    for i in range(1, chapter_count + 1):
        ch = epub.EpubHtml(
            title=f"第{i}章 测试章节",
            file_name=f"chapter_{i}.xhtml",
            lang="zh",
        )
        ch.content = f"""<h1>第{i}章 测试章节</h1>
<p>这是第{i}章的正文内容。用于自动化测试验证 EPUB 解析功能是否正常。</p>
<p>包含多个段落，测试 HTML 渲染效果。关键词：自动化测试、EPUB、LLM。</p>"""
        book.add_item(ch)
        chapters.append(ch)

    # spine
    book.toc = chapters
    book.spine = chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    tmp = tempfile.NamedTemporaryFile(suffix=".epub", delete=False)
    epub.write_epub(tmp.name, book)
    return tmp.name


def create_empty_epub() -> str:
    """生成一个无章节的空白 EPUB（用于负向测试）"""
    book = epub.EpubBook()
    book.set_identifier("empty-epub-001")
    book.set_title("空白书")
    book.set_language("zh")
    book.add_author("无人")

    book.spine = []
    book.toc = []
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    tmp = tempfile.NamedTemporaryFile(suffix=".epub", delete=False)
    epub.write_epub(tmp.name, book)
    return tmp.name
