"""Generate a clearly watermarked PDF only in this fixture directory."""
from pathlib import Path
import pymupdf

root = Path(__file__).parent
with pymupdf.open() as pdf:
    for body in (root.joinpath('synthetic_kyc_sop.txt').read_text(),
                 'SYNTHETIC DEMONSTRATION ONLY\nAppendix: Fictional review register\nRecord ID | Demo reviewer | Demo decision\nNo actual customer data.'):
        page = pdf.new_page()
        page.insert_textbox(pymupdf.Rect(40,40,550,800), body, fontsize=12)
    pdf.save(root / 'synthetic_kyc_sop.pdf')
