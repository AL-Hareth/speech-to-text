"""Dev tool: rebuild static fonts in app/assets/fonts from Google Fonts variable TTFs (OFL).

Usage: python tools/make_fonts.py <dir with naskh.ttf and inter.ttf>
Sources (github.com/google/fonts, ofl/): NotoNaskhArabic[wght].ttf, Inter[opsz,wght].ttf
SHA256 of sources used for the committed fonts:
  NotoNaskhArabic[wght].ttf 67b5a525a661b607971fbd3f96a81b89d3a768e74534fca84f18ac97e6fab72f
  Inter[opsz,wght].ttf      29160a80ff49ddcab2c97711247e08b1fab27a484a329ce8b813d820dc559031
"""
import hashlib
import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

EXPECTED = {
    "naskh.ttf": "67b5a525a661b607971fbd3f96a81b89d3a768e74534fca84f18ac97e6fab72f",
    "inter.ttf": "29160a80ff49ddcab2c97711247e08b1fab27a484a329ce8b813d820dc559031",
}
OUT = Path(__file__).resolve().parent.parent / "app" / "assets" / "fonts"


def main(src: Path) -> None:
    for fn, sha in EXPECTED.items():
        if hashlib.sha256((src / fn).read_bytes()).hexdigest() != sha:
            raise SystemExit(f"SHA256 mismatch for {fn}")
    for fn, name, axes in [("naskh.ttf", "NotoNaskhArabic", {}), ("inter.ttf", "Inter", {"opsz": 14})]:
        for wght, suf in [(400, "Regular"), (700, "Bold")]:
            inst = instancer.instantiateVariableFont(TTFont(src / fn), {"wght": wght, **axes})
            inst.save(OUT / f"{name}-{suf}.ttf")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
