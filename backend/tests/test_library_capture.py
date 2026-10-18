import unittest

from scripts.capture_library_corpus import normalize_html, source_metadata


class LibraryCaptureTest(unittest.TestCase):
    def test_normalization_preserves_inline_numbers_and_table_column_relationships(self):
        text, images = normalize_html('<h1>借阅</h1><p>可借<span>20</span>册。</p><table>'
            '<tr><td><p>读者类型</p></td><td>册数</td></tr>'
            '<tr><td>本科生</td><td><p>20</p></td></tr></table><img src="qrcode.png">')
        self.assertIn("可借20册。", text)
        self.assertIn("| 读者类型 | 册数 |", text)
        self.assertIn("| 本科生 | 20 |", text)
        self.assertEqual(images, 1)

    def test_extraction_does_not_include_script_style_or_claim_image_text(self):
        text, _ = normalize_html('<style>bad</style><script>bad</script><p>原文</p><img alt="未经OCR的数字">')
        self.assertEqual(text.strip(), "原文")

    def test_page_creation_and_update_dates_are_not_inferred_publication_dates(self):
        item = {"id": 1426, "title": "权限", "status": 1, "deleteFlag": 0,
            "createtime": "2021-12-18T00:00:00", "updatetime": "2025-06-12T00:00:00", "publishTime": None}
        result = source_metadata(item, "permissions", 1387, "borrowing", "2026-10-18T08:00:00+08:00", "a" * 64)
        self.assertIsNone(result["published_at"])
        self.assertIsNone(result["effective_at"])
        self.assertIn("id=1426", result["url"])


