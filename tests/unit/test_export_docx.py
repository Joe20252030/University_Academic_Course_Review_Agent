import pytest

from config import Settings
from export.docx import save_docx


def test_save_docx_raises_not_implemented() -> None:
	with pytest.raises(NotImplementedError):
		save_docx("# Sample\n\nHello", Settings())

