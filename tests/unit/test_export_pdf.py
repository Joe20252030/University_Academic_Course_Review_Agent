import pytest

from config import Settings
from export.pdf import save_pdf


def test_save_pdf_raises_not_implemented() -> None:
	with pytest.raises(NotImplementedError):
		save_pdf("# Sample\n\nHello", Settings())

