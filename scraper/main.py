from extractor import fetch_html
from parser import parse_html
from pathlib import Path

URL = "https://sklepsoltech.pl/pl/c/Panele-fotowoltaiczne/13"

html = fetch_html(URL)

output_dir = Path("data/raw/html")
output_dir.mkdir(parents=True, exist_ok=True)
(output_dir / "page.html").write_text(html, encoding="utf-8")

soup = parse_html(html)

print(soup.title.string)