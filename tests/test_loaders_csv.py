"""Tests for DocumentLoader CSV handling and load_and_split_classified edge cases."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest
from langchain_core.documents import Document

from uacragent.domain.types import DocumentType
from uacragent.infra.loaders import DocumentLoader
from uacragent.infra.settings import Settings


@pytest.fixture
def loader(tmp_path):
    return DocumentLoader(Settings(google_api_key="fake"))


# ---------------------------------------------------------------------------
# _load_csv
# ---------------------------------------------------------------------------

class TestLoadCsv:
    def test_empty_csv_returns_placeholder(self, loader, tmp_path):
        f = tmp_path / "empty.csv"
        f.write_text("", encoding="utf-8")
        docs = loader.load_single_file(str(f))
        assert len(docs) == 1
        assert "empty CSV" in docs[0].page_content

    def test_header_only_csv(self, loader, tmp_path):
        f = tmp_path / "header_only.csv"
        f.write_text("Name,Age,Score\n", encoding="utf-8")
        docs = loader.load_single_file(str(f))
        assert len(docs) == 1
        assert "Name" in docs[0].page_content

    def test_small_csv_single_chunk(self, loader, tmp_path):
        f = tmp_path / "small.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["Name", "Score"])
            for i in range(5):
                writer.writerow([f"Student{i}", i * 10])
        docs = loader.load_single_file(str(f))
        assert len(docs) == 1
        assert "Name | Score" in docs[0].page_content

    def test_large_csv_chunked_by_rows(self, loader, tmp_path):
        f = tmp_path / "large.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["id", "value"])
            for i in range(25):
                writer.writerow([i, f"val{i}"])
        docs = loader.load_single_file(str(f))
        # 25 rows / 10 per chunk = 3 chunks
        assert len(docs) == 3

    def test_csv_chunks_include_header(self, loader, tmp_path):
        f = tmp_path / "data.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["col1", "col2"])
            for i in range(15):
                writer.writerow([i, f"v{i}"])
        docs = loader.load_single_file(str(f))
        # Every chunk must contain the header
        for doc in docs:
            assert "col1 | col2" in doc.page_content

    def test_csv_chunk_row_range_in_content(self, loader, tmp_path):
        f = tmp_path / "ranged.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["x"])
            for i in range(12):
                writer.writerow([i])
        docs = loader.load_single_file(str(f))
        # First chunk covers rows 1–10, second covers 11–12
        assert "rows 1–10" in docs[0].page_content
        assert "rows 11–12" in docs[1].page_content

    def test_csv_source_metadata(self, loader, tmp_path):
        f = tmp_path / "meta.csv"
        f.write_text("a,b\n1,2\n", encoding="utf-8")
        docs = loader.load_single_file(str(f))
        assert docs[0].metadata["source"] == str(f)


# ---------------------------------------------------------------------------
# load_and_split_classified — no workspace copy
# ---------------------------------------------------------------------------

class TestLoadAndSplitClassified:
    def test_no_workspace_paths_does_not_copy(self, loader, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("direct load content")
        classified = {DocumentType.other: [str(f)]}
        chunks = loader.load_and_split_classified(classified, workspace_paths=None)
        assert len(chunks) >= 1
        assert all(c.metadata["source"] == str(f) for c in chunks)

    def test_empty_classified_returns_no_chunks(self, loader):
        chunks = loader.load_and_split_classified({})
        assert chunks == []

    def test_unsupported_file_raises_ingest_error(self, loader, tmp_path):
        from uacragent.domain.errors import IngestError
        f = tmp_path / "data.xyz"
        f.write_text("bad ext")
        classified = {DocumentType.other: [str(f)]}
        with pytest.raises(IngestError):
            loader.load_and_split_classified(classified)

    def test_doc_type_metadata_stamped(self, loader, tmp_path):
        f = tmp_path / "syllabus.txt"
        f.write_text("# Grading\n\nFinal: 50%\nMidterm: 30%\n")
        classified = {DocumentType.syllabus: [str(f)]}
        chunks = loader.load_and_split_classified(classified)
        assert all(c.metadata.get("doc_type") == "syllabus" for c in chunks)

    def test_multiple_doc_types_all_chunked(self, loader, tmp_path):
        f1 = tmp_path / "lec.txt"
        f1.write_text("lecture content " * 50)
        f2 = tmp_path / "exam.txt"
        f2.write_text("exam content " * 50)
        classified = {
            DocumentType.lecture_note: [str(f1)],
            DocumentType.past_exam: [str(f2)],
        }
        chunks = loader.load_and_split_classified(classified)
        doc_types = {c.metadata["doc_type"] for c in chunks}
        assert "lecture_note" in doc_types
        assert "past_exam" in doc_types
