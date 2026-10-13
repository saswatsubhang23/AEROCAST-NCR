"""Shared helpers for knowledge-base tests: a deterministic embedder and a tiny PDF writer."""

import math
import re
import zlib


class FakeEmbedder:
    """Hashed bag-of-words vectors: texts sharing distinctive words score high, unrelated texts score near zero.
    Lets the real Chroma store and ranking logic be tested without a model."""

    DIM = 4096
    STOP = {"the", "and", "with", "for", "how", "are", "that", "this", "from", "what", "does", "you", "was", "into", "can"}

    def __init__(self, model: str = "fake-embed"):
        self.model = model
        self.calls = 0
        self.fail_with: Exception | None = None
        self.on_embed = None  # optional hook, runs inside embed_documents

    @staticmethod
    def _vec(text: str) -> list[float]:
        v = [0.0] * FakeEmbedder.DIM
        for w in re.findall(r"[a-z0-9]{3,}", text.lower()):
            if w not in FakeEmbedder.STOP:
                v[zlib.crc32(w.encode()) % FakeEmbedder.DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def embed_documents(self, texts):
        self.calls += 1
        if self.on_embed:
            self.on_embed()
        if self.fail_with:
            raise self.fail_with
        return [self._vec(t) for t in texts]

    async def embed_query(self, text):
        if self.fail_with:
            raise self.fail_with
        return self._vec(text)

    async def check(self):
        if self.fail_with:
            raise self.fail_with


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one line of text per page (an empty string gives a blank page)."""
    n = len(pages)
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{4 + 2 * i} 0 R' for i in range(n))}] /Count {n} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(pages):
        content = f"BT /F1 12 Tf 72 720 Td ({_esc(text)}) Tj ET".encode() if text else b""
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {5 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 3 0 R >> >> >>".encode()
        )
        objs.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


PM25 = (
    "The WHO air quality guideline for annual mean PM2.5 is 5 micrograms per cubic metre. "
    "Fine particulate matter PM2.5 penetrates deep into the lungs and bloodstream. "
) * 3
INVERSION = (
    "A temperature inversion traps pollutants near the ground because warm air above acts like a lid. "
    "Inversions are common on cold winter nights with clear skies and calm winds in the Indo-Gangetic plain. "
) * 3
BAKING = "Sourdough bread needs flour water salt and a starter, then a long overnight rise before baking in a hot oven. " * 3
