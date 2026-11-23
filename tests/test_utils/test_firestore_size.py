"""utils/firestore_client.py のドキュメントサイズ見積もりテスト"""

from datetime import datetime, timezone

from utils.firestore_client import estimate_document_size, estimate_value_size


class TestEstimateValueSize:
    def test_scalars(self):
        assert estimate_value_size(None) == 1
        assert estimate_value_size(True) == 1
        assert estimate_value_size(1) == 8
        assert estimate_value_size(0.123456789) == 8
        assert estimate_value_size(datetime.now(timezone.utc)) == 8

    def test_string_counts_utf8_bytes_plus_one(self):
        assert estimate_value_size("abc") == 4
        assert estimate_value_size("あ") == 4  # UTF-8で3バイト

    def test_float_array_is_eight_bytes_per_element(self):
        """embedding を JSON 長で見積もらない（768次元 = 6144バイト）"""
        assert estimate_value_size([0.0123456789] * 768) == 768 * 8

    def test_map_counts_field_names(self):
        assert estimate_value_size({"ab": 1}) == 3 + 8
        assert estimate_value_size({"a": {"b": "c"}}) == 2 + (2 + 2)

    def test_document_adds_overhead(self):
        assert estimate_document_size({}) == 32
