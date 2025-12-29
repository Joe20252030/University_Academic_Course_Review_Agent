from pathlib import Path
from datetime import datetime
from config import Settings

def save_markdown(md_text: str, settings: Settings) -> str:
    Path(settings.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    path = Path(settings.OUTPUT_DIR) / f"review_{datetime.now().isoformat()}.md"
    path.write_text(md_text, encoding="utf-8")
    return str(path)
