import gzip
import json

from ingestion.jsonl import dumps_gzipped


def test_dumps_gzipped_writes_one_json_object_per_line():
    payload = dumps_gzipped([{"a": 1}, {"b": "é"}])
    lines = gzip.decompress(payload).decode("utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [{"a": 1}, {"b": "é"}]


def test_dumps_gzipped_preserves_non_ascii_characters():
    payload = dumps_gzipped([{"nom": "drépanocytose"}])
    assert "drépanocytose" in gzip.decompress(payload).decode("utf-8")


def test_dumps_gzipped_handles_an_empty_list():
    assert gzip.decompress(dumps_gzipped([])) == b""
