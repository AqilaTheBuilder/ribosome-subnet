"""Merge cover + body into the final proposal PDF (cover normalized to A4)."""
from pathlib import Path

from pypdf import PdfReader, PdfWriter

SCRIPTS = Path("/home/z/my-project/scripts")
REPO = Path("/home/z/my-project/download/ribosome-network")
OUT = REPO / "docs" / "PROPOSAL.pdf"

A4_W, A4_H = 595.28, 841.89


def normalize(page):
    box = page.mediabox
    w, h = float(box.width), float(box.height)
    if abs(w - A4_W) > 0.4 or abs(h - A4_H) > 0.4:
        page.scale_to(A4_W, A4_H)
    return page


def main() -> None:
    writer = PdfWriter()
    cover = PdfReader(SCRIPTS / "proposal_cover.pdf").pages[0]
    writer.add_page(normalize(cover))
    body = PdfReader(SCRIPTS / "proposal_body.pdf")
    for page in body.pages:
        writer.add_page(normalize(page))
    writer.add_metadata({
        "/Title": "Ribosome Network - A Decentralized RNA Inverse-Folding Subnet",
        "/Author": "Z.ai",
        "/Creator": "Z.ai",
        "/Subject": "Bittensor Global Subnet Hackathon 2026 - Checkpoint 1 Subnet Proposal",
    })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("wb") as f:
        writer.write(f)
    import os

    print(f"final: {OUT} ({os.path.getsize(OUT)/1024:.0f} KB, "
          f"{len(writer.pages)} pages)")


if __name__ == "__main__":
    main()
