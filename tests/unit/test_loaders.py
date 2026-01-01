from pathlib import Path

import pytest

from ingest.loaders import load_documents


def test_load_documents_txt_and_md(tmp_path: Path) -> None:
	txt_path = tmp_path / "sample.txt"
	md_path = tmp_path / "sample.md"

	txt_path.write_text("Hello from txt\nSecond line\n", encoding="utf-8")
	md_path.write_text("# Title\n\nHello from md\n", encoding="utf-8")

	docs = load_documents([str(txt_path), str(md_path)])

	assert len(docs) == 2
	joined = "\n".join(d.page_content for d in docs)
	assert "Hello from txt" in joined
	assert "Hello from md" in joined


def test_load_documents_pdf_fixture() -> None:
	pdf_path = (
		Path(__file__).resolve().parents[2]
		/ "fixtures"
		/ "outlines"
		/ "MGTA01 Course Outline - MShibaeva (Fall 2025) - updated.pdf"
	)
	assert pdf_path.exists(), f"Missing PDF fixture at {pdf_path}"

	docs = load_documents([str(pdf_path)])
	assert len(docs) > 0
	assert any((d.page_content or "").strip() for d in docs)


def test_load_documents_unsupported_extension(tmp_path: Path) -> None:
	bad_path = tmp_path / "unsupported.docx"
	bad_path.write_text("not a real docx", encoding="utf-8")

	with pytest.raises(ValueError, match=r"Unsupported file type"):
		load_documents([str(bad_path)])

