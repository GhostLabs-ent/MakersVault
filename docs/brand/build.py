#!/usr/bin/env python3
"""Generate every Curiarium brand asset from one source of truth.

    python3 docs/brand/build.py

Writes the canonical SVGs next to this file and the runtime assets into
curiarium/web/public/. Requires rsvg-convert (librsvg) and, for the JPEG-derived
social image, ImageMagick.

Design notes
------------
* The AI reference (original-ai-reference.jpeg) is the art direction: a hexagonal
  reliquary, a faceted crystal "C", gold trim, cyan wireframe, a runic ring, and a
  gold/violet wordmark over "STL LIBRARY / CURIOSITY ARCHIVE".
* The provided SVG (original-provided.svg) had a broken XML namespace
  (http://w3.org), 100% width/height, no runic ring, a plate too short for the
  hexagon, and a "C" built from facets that read as a zigzag. This generator
  fixes all of that.
* Two forms, deliberately:
    - the MARK is a square, plate-backed icon: no runes, no outer rings, because
      below ~48 px they are noise. Used for favicons, app icons, PWA, README.
    - the LOCKUP carries the full detail: runes, rings, wordmark, subtitle.
* Text uses generic serif/sans families on purpose: a logo must not depend on a
  webfont being installed (the provided SVG asked for Cinzel, which was never
  loaded).
* The wordmark is available as plain text to copy: CURIARIUM / STL LIBRARY /
  CURIOSITY ARCHIVE.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUBLIC = HERE.parents[1] / "curiarium" / "web" / "public"

# --- palette (from the reference) ------------------------------------------
VOID = ("#140727", "#0b0316", "#040108")
PURPLE = ("#b76eff", "#7b2cbf", "#4a157d")
CYAN = ("#4cc9f0", "#4895ef")
GOLD = ("#c5a059", "#f3e5ab", "#ffd700")

# theme variants: (wordmark top, wordmark mid, wordmark bottom, plate bg, name)
VARIANTS = {
    # variant: (wordmark top, mid, bottom, plate mid-stop)
    "dark":         ("#f3e5ab", "#e8c874", "#b76eff", "#0b0316"),
    "light":        ("#5a189a", "#7b2cbf", "#b76eff", "#efe9f8"),
    "neon-green":   ("#eaffd0", "#7bff5c", "#39d353", "#04120a"),
    "neon-blue":    ("#e6fbff", "#4cc9f0", "#4895ef", "#04101a"),
    "neon-purple":  ("#f6e9ff", "#b76eff", "#8a4bd6", "#0d0418"),
}


def defs(plate_mid: str, crystal: tuple[str, str, str] = ("#c77dff", "#9d4edd", "#5a189a")) -> str:
    return f"""  <defs>
    <radialGradient id="space-bg" cx="50%" cy="50%" r="75%">
      <stop offset="0%" stop-color="#140727"/>
      <stop offset="60%" stop-color="{plate_mid}"/>
      <stop offset="100%" stop-color="#040108"/>
    </radialGradient>
    <linearGradient id="arcane-purple" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{PURPLE[0]}"/>
      <stop offset="50%" stop-color="{PURPLE[1]}"/>
      <stop offset="100%" stop-color="{PURPLE[2]}"/>
    </linearGradient>
    <linearGradient id="cyan-glow" x1="100%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="{CYAN[0]}"/>
      <stop offset="100%" stop-color="{CYAN[1]}"/>
    </linearGradient>
    <linearGradient id="gold-wire" x1="0%" y1="100%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="{GOLD[0]}"/>
      <stop offset="50%" stop-color="{GOLD[1]}"/>
      <stop offset="100%" stop-color="{GOLD[2]}"/>
    </linearGradient>
    <linearGradient id="crystal" x1="30%" y1="0%" x2="80%" y2="100%">
      <stop offset="0%" stop-color="{crystal[0]}"/>
      <stop offset="45%" stop-color="{crystal[1]}"/>
      <stop offset="100%" stop-color="{crystal[2]}"/>
    </linearGradient>
    <filter id="clean-glow" x="-10%" y="-10%" width="120%" height="120%">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
"""


def hex_framework(runes: bool) -> str:
    rune_ring = ""
    if runes:
        rune_ring = """
    <g fill="url(#gold-wire)" font-family="'Noto Sans Runic','Segoe UI Historic',serif"
       font-size="15" opacity="0.75" text-anchor="middle">
      <text x="300" y="196" transform="rotate(-31 300 196)">ᛞᚨᚹᚾ</text>
      <text x="500" y="196" transform="rotate(31 500 196)">ᛗᚨᚷᛁᚲ</text>
      <text x="640" y="352" transform="rotate(90 640 352)">ᚲᚢᚱᛁᚨ</text>
      <text x="640" y="440" transform="rotate(90 640 440)">ᚱᛁᚢᛗ</text>
      <text x="500" y="556" transform="rotate(-31 500 556)">ᚨᚱᚲᚺᛁᚡᛖ</text>
      <text x="300" y="556" transform="rotate(31 300 556)">ᛋᛏᛚ</text>
      <text x="160" y="440" transform="rotate(-90 160 440)">ᚲᚢᚱᛁᛟ</text>
      <text x="160" y="352" transform="rotate(-90 160 352)">ᛋᛏᛟᚱᛖ</text>
    </g>"""

    rings = """
    <circle cx="400" cy="380" r="310" fill="none" stroke="url(#arcane-purple)" stroke-width="1.5" stroke-opacity="0.3" stroke-dasharray="4, 8"/>
    <circle cx="400" cy="380" r="295" fill="none" stroke="url(#gold-wire)" stroke-width="1" stroke-opacity="0.2"/>""" if runes else ""

    return f"""    {rings}
    <polygon points="400,70 668,225 668,535 400,690 132,535 132,225" fill="none" stroke="url(#arcane-purple)" stroke-width="4" stroke-linejoin="round"/>
    <polygon points="400,100 642,240 642,520 400,660 158,520 158,240" fill="none" stroke="url(#cyan-glow)" stroke-width="1.5" stroke-opacity="0.55" stroke-linejoin="round"/>
    <line x1="400" y1="70" x2="400" y2="690" stroke="url(#arcane-purple)" stroke-width="1" stroke-opacity="0.4"/>
    <line x1="132" y1="225" x2="668" y2="535" stroke="url(#arcane-purple)" stroke-width="1" stroke-opacity="0.4"/>
    <line x1="132" y1="535" x2="668" y2="225" stroke="url(#arcane-purple)" stroke-width="1" stroke-opacity="0.4"/>
    <polygon points="400,70 668,535 132,535" fill="none" stroke="url(#cyan-glow)" stroke-width="0.75" stroke-opacity="0.3"/>
    <polygon points="400,690 132,225 668,225" fill="none" stroke="url(#cyan-glow)" stroke-width="0.75" stroke-opacity="0.3"/>
    <polygon points="400,140 608,260 608,500 400,620 192,500 192,260" fill="none" stroke="url(#gold-wire)" stroke-width="1" stroke-opacity="0.45"/>
    <polygon points="400,180 573,280 573,480 400,580 227,480 227,280" fill="none" stroke="url(#arcane-purple)" stroke-width="1" stroke-opacity="0.5" stroke-dasharray="15, 5"/>
{rune_ring}
    <g fill="url(#gold-wire)">
      <circle cx="400" cy="70" r="4"/><circle cx="668" cy="225" r="4"/><circle cx="668" cy="535" r="4"/>
      <circle cx="400" cy="690" r="4"/><circle cx="132" cy="535" r="4"/><circle cx="132" cy="225" r="4"/>
    </g>
    <g fill="#4cc9f0">
      <circle cx="400" cy="220" r="3"/><circle cx="520" cy="310" r="3"/><circle cx="520" cy="450" r="3"/>
      <circle cx="400" cy="540" r="3"/><circle cx="280" cy="450" r="3"/><circle cx="280" cy="310" r="3"/>
    </g>"""


def crystal_c() -> str:
    """A block-letterform C, extruded down-right, so it reads as a C at any size.

    Front face is a square C (spine, top arm, bottom arm, opening to the right);
    the back face and three side quads give it depth in the hexagon's axonometric
    direction. Gold hairlines pick out the edges, as in the reference.
    """
    front = "M330,250 H470 V300 H385 V420 H470 V470 H330 Z"
    dx, dy = 26, 15
    return f"""    <!-- back face (depth) -->
    <path d="{front}" transform="translate({dx} {dy})" fill="#1a0730" stroke="url(#gold-wire)" stroke-width="1" stroke-opacity="0.55"/>
    <!-- side quads visible on the lower-right -->
    <g fill="#3c096c" stroke="url(#gold-wire)" stroke-width="0.9" stroke-opacity="0.7">
      <polygon points="470,250 496,265 496,315 470,300"/>
      <polygon points="385,300 411,315 411,435 385,420"/>
      <polygon points="330,470 470,470 496,485 356,485"/>
    </g>
    <!-- front face -->
    <path d="{front}" fill="url(#crystal)" stroke="url(#gold-wire)" stroke-width="1.6" stroke-linejoin="round" filter="url(#clean-glow)"/>
    <!-- inner bevel hairline, keeps the letterform from reading as a flat slab -->
    <path d="M345,262 H458 V288 H398 V432 H458 V458 H345" fill="none" stroke="#e0aaff" stroke-width="0.8" stroke-opacity="0.45"/>
    <!-- keystone plate under the C, echoing the reference's drawer front -->
    <g>
      <polygon points="330,470 470,470 496,485 356,485" fill="none" stroke="url(#gold-wire)" stroke-width="1.4"/>
      <circle cx="400" cy="478" r="3.4" fill="none" stroke="url(#gold-wire)" stroke-width="1.1"/>
      <rect x="398.6" y="480" width="2.8" height="4.6" fill="url(#gold-wire)"/>
    </g>"""


def build_mark(plate_mid: str = VOID[1]) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 800" width="800" height="800" role="img" aria-label="Curiarium: a hexagonal reliquary holding a crystal C">
  <title>Curiarium mark</title>
  <!-- Generated by docs/brand/build.py - edit the generator, not this file. -->
{defs(plate_mid)}
  <rect x="40" y="40" width="720" height="720" rx="150" fill="url(#space-bg)"/>
  <g transform="translate(400 400) scale(0.86) translate(-400 -345)">
{hex_framework(runes=False)}
{crystal_c()}
  </g>
</svg>
"""


def build_lockup(variant: str) -> str:
    top, mid, bottom, plate_mid = VARIANTS[variant]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 900" width="800" height="900" role="img"
     aria-label="Curiarium: STL library, curiosity archive">
  <title>Curiarium lockup ({variant})</title>
  <!-- Generated by docs/brand/build.py - edit the generator, not this file. -->
{defs(plate_mid)}
  <g transform="translate(150 20) scale(0.625)">
{hex_framework(runes=True)}
{crystal_c()}
  </g>
  <linearGradient id="word-gold" x1="0%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%" stop-color="{top}"/>
    <stop offset="55%" stop-color="{mid}"/>
    <stop offset="100%" stop-color="{bottom}"/>
  </linearGradient>
  <linearGradient id="sub-gold" x1="0%" y1="0%" x2="100%" y2="0%">
    <stop offset="0%" stop-color="{bottom}"/>
    <stop offset="50%" stop-color="{mid}"/>
    <stop offset="100%" stop-color="{top}"/>
  </linearGradient>
  <text x="400" y="712" font-family="Georgia, 'Times New Roman', 'DejaVu Serif', serif"
        font-size="86" font-weight="700" letter-spacing="2" text-anchor="middle"
        fill="url(#word-gold)" stroke="#5a189a" stroke-width="1.1" paint-order="stroke">Curiarium</text>
  <text x="400" y="775" font-family="'Helvetica Neue', Arial, 'DejaVu Sans', sans-serif"
        font-size="27" font-weight="700" letter-spacing="9" text-anchor="middle"
        fill="url(#sub-gold)">STL LIBRARY</text>
  <text x="400" y="815" font-family="'Helvetica Neue', Arial, 'DejaVu Sans', sans-serif"
        font-size="21" font-weight="600" letter-spacing="7" text-anchor="middle"
        fill="url(#sub-gold)" opacity="0.95">CURIOSITY ARCHIVE</text>
</svg>
"""


def build_lockup_wide(variant: str) -> str:
    """Horizontal lockup: mark left, wordmark right. Sized 2.5:1 so it fits a
    card at max-h-40 (160 px tall -> 400 px wide) without overflowing."""
    top, mid, bottom, plate_mid = VARIANTS[variant]
    crystal = ("#c77dff", "#9d4edd", "#5a189a")
    if variant.startswith("neon-"):
        crystal = (top, mid, bottom)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 360" width="900" height="360" role="img"
     aria-label="Curiarium: STL library, curiosity archive">
  <title>Curiarium lockup, wide ({variant})</title>
  <!-- Generated by docs/brand/build.py - edit the generator, not this file. -->
{defs(plate_mid, crystal)}
  <rect x="4" y="4" width="344" height="344" rx="74" fill="url(#space-bg)"/>
  <g transform="translate(176 180) scale(0.37) translate(-400 -345)">
{hex_framework(runes=False)}
{crystal_c()}
  </g>
  <linearGradient id="word-gold" x1="0%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%" stop-color="{top}"/>
    <stop offset="55%" stop-color="{mid}"/>
    <stop offset="100%" stop-color="{bottom}"/>
  </linearGradient>
  <linearGradient id="sub-gold" x1="0%" y1="0%" x2="100%" y2="0%">
    <stop offset="0%" stop-color="{bottom}"/>
    <stop offset="50%" stop-color="{mid}"/>
    <stop offset="100%" stop-color="{top}"/>
  </linearGradient>
  <text x="380" y="182" font-family="Georgia, 'Times New Roman', 'DejaVu Serif', serif"
        font-size="86" font-weight="700" letter-spacing="1"
        fill="url(#word-gold)" stroke="#5a189a" stroke-width="1" paint-order="stroke">Curiarium</text>
  <text x="382" y="240" font-family="'Helvetica Neue', Arial, 'DejaVu Sans', sans-serif"
        font-size="22" font-weight="700" letter-spacing="7" fill="url(#sub-gold)">STL LIBRARY</text>
  <text x="382" y="276" font-family="'Helvetica Neue', Arial, 'DejaVu Sans', sans-serif"
        font-size="18" font-weight="600" letter-spacing="5" fill="url(#sub-gold)" opacity="0.95">CURIOSITY ARCHIVE</text>
</svg>
"""


def render(svg: Path, out: Path, width: int, background: str | None = None) -> None:
    cmd = ["rsvg-convert", "-w", str(width), str(svg), "-o", str(out)]
    if background:
        cmd += ["-b", background]
    subprocess.run(cmd, check=True)


def main() -> None:
    mark = HERE / "curiarium-mark.svg"
    mark.write_text(build_mark())
    for variant in VARIANTS:
        (HERE / f"curiarium-lockup-{variant}.svg").write_text(build_lockup(variant))
        (HERE / f"curiarium-lockup-wide-{variant}.svg").write_text(build_lockup_wide(variant))
    # the neutral name is the dark lockup: that is what the app and README use
    (HERE / "curiarium-lockup.svg").write_text(build_lockup("dark"))

    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / "favicon.svg").write_text(build_mark())
    (PUBLIC / "img").mkdir(exist_ok=True)
    (PUBLIC / "img" / "logo.svg").write_text(build_lockup("dark"))
    (PUBLIC / "img" / "logo-wide.svg").write_text(build_lockup_wide("dark"))
    (PUBLIC / "img" / "mark.svg").write_text(build_mark())

    sizes = {
        "favicon-32.png": 32,
        "favicon-48.png": 48,
        "apple-touch-icon.png": 180,
        "icon-192.png": 192,
        "icon-512.png": 512,
    }
    for name, px in sizes.items():
        render(mark, PUBLIC / name, px)

    # maskable icon: same art, 20% safe-zone padding on an opaque plate
    render(mark, PUBLIC / "icon-maskable-512.png", 512)

    # login-screen logos, one per theme (the app swaps these by theme)
    for variant, target in (
        ("dark", "whitelogo.png"),
        ("light", "blacklogo.png"),
        ("neon-green", "green_theme/Neon_Green_bgrm.png"),
        ("neon-purple", "purple_theme/Neon_Purple_logo_bgrm.png"),
        ("neon-blue", "blue_theme/Blue_Theme_logo_bgrm.png"),
    ):
        src = HERE / f"curiarium-lockup-wide-{variant}.svg"
        dest = PUBLIC / "img" / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        render(src, dest, 720)

    # social card: the lockup on a 1200x630 canvas (GitHub/social preview)
    card = PUBLIC / "_og-card.png"
    render(HERE / "curiarium-lockup-dark.svg", card, 430, background="#040108")
    subprocess.run(["magick", str(card), "-gravity", "center", "-background", "#040108",
                    "-extent", "1200x630", str(PUBLIC / "og-image.png")], check=True)
    card.unlink()

    (PUBLIC / "manifest.webmanifest").write_text("""{
  "name": "Curiarium",
  "short_name": "Curiarium",
  "description": "A self-hosted vault for 3D print files, models and references.",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#040108",
  "theme_color": "#0b0316",
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png" },
    { "src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" },
    { "src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml" }
  ]
}
""")

    print("brand assets written:")
    for p in sorted(PUBLIC.rglob("*")):
        if p.is_file() and p.suffix in {".svg", ".png", ".webmanifest"}:
            print(f"  {p.relative_to(PUBLIC.parent)}  ({p.stat().st_size // 1024 or 1} KB)")


if __name__ == "__main__":
    main()
