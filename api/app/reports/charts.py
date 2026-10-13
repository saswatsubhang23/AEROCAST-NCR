"""SVG figures for the exported report. Plain shapes and attributes only (no CSS, gradients or scripts), so the same markup is
drawn by a browser and embedded in the PDF. Every figure is drawn from numbers passed in; a missing value is a gap, never a
filled-in line.
"""

from __future__ import annotations

import math
from datetime import datetime
from xml.sax.saxutils import escape

from app.core.time import to_ist

INK, MUTED, GRID, ACCENT = "#1b2433", "#5c6b82", "#d5dbe6", "#0e7490"
PALETTE = ["#0e7490", "#d97706", "#7c3aed", "#059669", "#dc2626", "#2563eb"]
FONT = "Helvetica, Arial, sans-serif"
RAMP = ["#ffffcc", "#fed976", "#fd8d3c", "#e31a1c", "#800026", "#3b0030"]


def _t(x: float, y: float, s: str, *, size: float = 10, anchor: str = "start", fill: str = MUTED, weight: str = "normal", rotate: float | None = None) -> str:
    tr = f' transform="rotate({rotate:g} {x:.1f} {y:.1f})"' if rotate else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size:g}" text-anchor="{anchor}" fill="{fill}" font-weight="{weight}"{tr}>{escape(s)}</text>'


def _svg(w: int, h: int, body: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}"><rect x="0" y="0" width="{w}" height="{h}" fill="#ffffff"/>{body}</svg>'


def fmt(v: float) -> str:
    if v == 0:
        return "0"
    a = abs(v)
    return f"{v:.0f}" if a >= 100 else f"{v:.1f}" if a >= 10 else f"{v:.2f}".rstrip("0").rstrip(".")


def nice_ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    if not math.isfinite(lo) or not math.isfinite(hi):
        return []
    if hi <= lo:
        hi = lo + 1.0
    raw = (hi - lo) / max(1, n)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    ticks, v = [], start
    while v <= hi + step * 0.001:
        ticks.append(round(v, 10))
        v += step
    return ticks


def ramp(t: float) -> str:
    """A 0..1 position on the sequential colour ramp (light = low, dark = high)."""
    t = 0.0 if not math.isfinite(t) else min(1.0, max(0.0, t))
    pos = t * (len(RAMP) - 1)
    k = min(len(RAMP) - 2, int(pos))
    f = pos - k
    a, b = RAMP[k], RAMP[k + 1]
    c = [round(int(a[i:i + 2], 16) * (1 - f) + int(b[i:i + 2], 16) * f) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(c)


# ---- time series ----------------------------------------------------------------------------------------------------
def line_chart(times: list[datetime], series: list[tuple[str, list[float | None], str | None]], unit: str, *, width: int = 720, height: int = 250,
               zero_based: bool = False, step_note: str = "IST") -> str:
    """One or more hourly series on a shared time axis. Runs of consecutive values are joined; a gap stays a gap."""
    known = [v for _, vals, _ in series for v in vals if v is not None and math.isfinite(v)]
    if not times or not known:
        return _svg(width, 60, _t(width / 2, 34, "No values to draw", anchor="middle", size=12))
    lo, hi = min(known), max(known)
    if zero_based:
        lo = min(0.0, lo)
    pad = (hi - lo) * 0.08 or 1.0
    lo, hi = (lo if zero_based and lo == 0 else lo - pad), hi + pad
    ticks = nice_ticks(lo, hi, 4)
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
    ml, mr, mt, mb = 52, 14, 14, 44 if len(series) > 1 else 36
    pw, ph = width - ml - mr, height - mt - mb
    n = len(times)

    def X(i: int) -> float:
        return ml + pw * i / max(1, n - 1)

    def Y(v: float) -> float:
        return mt + ph - (v - lo) / (hi - lo) * ph

    out = []
    for tv in ticks:
        y = Y(tv)
        out.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{ml + pw}" y2="{y:.1f}" stroke="{GRID}" stroke-width="0.6"/>')
        out.append(_t(ml - 6, y + 3.5, fmt(tv), anchor="end", size=9))
    # time axis: roughly six labelled ticks, a day boundary marked with its date
    step = max(1, round(n / 6))
    for i in range(0, n, step):
        x = X(i)
        ts = to_ist(times[i])
        out.append(f'<line x1="{x:.1f}" y1="{mt + ph}" x2="{x:.1f}" y2="{mt + ph + 4}" stroke="{MUTED}" stroke-width="0.6"/>')
        out.append(_t(x, mt + ph + 16, ts.strftime("%d %b %H:%M") if n > 36 else ts.strftime("%H:%M"), anchor="middle", size=9))
    out.append(_t(ml, mt + ph + 30, f"Time ({step_note})", size=8.5))
    out.append(_t(12, mt + ph / 2, unit, size=9, anchor="middle", rotate=-90))
    for si, (label, vals, colour) in enumerate(series):
        c = colour or PALETTE[si % len(PALETTE)]
        run: list[tuple[float, float]] = []

        def flush() -> None:
            if len(run) >= 2:
                pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in run)
                out.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="1.8" stroke-linejoin="round"/>')
            elif len(run) == 1:
                out.append(f'<circle cx="{run[0][0]:.1f}" cy="{run[0][1]:.1f}" r="2.4" fill="{c}"/>')
            run.clear()

        for i, v in enumerate(vals[:n]):
            if v is None or not math.isfinite(v):
                flush()
            else:
                run.append((X(i), Y(v)))
        flush()
    if len(series) > 1:
        x = ml
        for si, (label, _, colour) in enumerate(series):
            c = colour or PALETTE[si % len(PALETTE)]
            out.append(f'<rect x="{x}" y="{height - 10}" width="10" height="3" fill="{c}"/>')
            out.append(_t(x + 14, height - 6, label, size=9, fill=INK))
            x += 22 + 5.4 * len(label)
    return _svg(width, height, "".join(out))


# ---- horizontal bars ------------------------------------------------------------------------------------------------
def hbar_chart(items: list[tuple[str, float, str | None, str]], unit: str, *, width: int = 720, vmax: float | None = None) -> str:
    """Rows of (label, value, colour, right-hand note). Longest bar scales to the widest value (or `vmax`)."""
    if not items:
        return _svg(width, 60, _t(width / 2, 34, "No values to draw", anchor="middle", size=12))
    row = 20
    ml, mr, mt = 235, 70, 8
    height = mt + row * len(items) + 24
    top = vmax or max(v for _, v, _, _ in items) or 1.0
    pw = width - ml - mr
    out = [f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{mt + row * len(items)}" stroke="{MUTED}" stroke-width="0.8"/>']
    for k, (label, v, colour, note) in enumerate(items):
        y = mt + k * row
        w = max(1.0, pw * 0.8 * min(v, top) / top)
        out.append(_t(ml - 8, y + 13, label if len(label) <= 40 else label[:39] + "…", anchor="end", size=9.5, fill=INK))
        out.append(f'<rect x="{ml}" y="{y + 3}" width="{w:.1f}" height="{row - 7}" fill="{colour or ACCENT}"/>')
        out.append(_t(ml + w + 6, y + 13, f"{fmt(v)} {unit}", size=9.5, fill=INK))
        if note:
            out.append(_t(width - 8, y + 13, note, size=8.5, anchor="end"))
    out.append(_t(ml, height - 8, f"Bar length is proportional to the value ({unit}), starting at zero.", size=8.5))
    return _svg(width, height, "".join(out))


# ---- map of a lattice field with wind arrows ------------------------------------------------------------------------
def field_map(lats: list[float], lons: list[float], grid: list[list[float | None]], unit: str, *, width: int = 720,
              arrows: tuple[list[float], list[float], list[list[float | None]], list[list[float | None]]] | None = None,
              points: list[tuple[float, float, float | None, str]] | None = None, marker: tuple[float, float, str] | None = None,
              vmin: float | None = None, vmax: float | None = None, arrow_unit: str = "m/s") -> str:
    """A lattice field drawn as cells on an equirectangular frame (x proportional to longitude times cos(latitude)), with optional
    wind arrows (lats, lons, u, v), station dots coloured on the same scale, and one marked place. The scale is the field's own
    range unless vmin/vmax are given, and the legend says so."""
    south, north, west, east = lats[0], lats[-1], lons[0], lons[-1]
    asp = math.cos(math.radians((south + north) / 2))
    ml, mr, mt, mb = 48, 78, 16, 40
    pw = width - ml - mr
    ph = pw * (north - south) / ((east - west) * asp)
    height = int(ph + mt + mb)
    vals = [v for row in grid for v in row if v is not None and math.isfinite(v)]
    lo = vmin if vmin is not None else (min(vals) if vals else 0.0)
    hi = vmax if vmax is not None else (max(vals) if vals else 1.0)
    if hi <= lo:
        hi = lo + 1.0

    def X(lon: float) -> float:
        return ml + pw * (lon - west) / (east - west)

    def Y(lat: float) -> float:
        return mt + ph * (north - lat) / (north - south)

    dlat = (north - south) / max(1, len(lats) - 1)
    dlon = (east - west) / max(1, len(lons) - 1)
    out = []
    for r, la in enumerate(lats):
        for c, lo_ in enumerate(lons):
            v = grid[r][c] if r < len(grid) and c < len(grid[r]) else None
            x0, x1 = X(max(west, lo_ - dlon / 2)), X(min(east, lo_ + dlon / 2))
            y0, y1 = Y(min(north, la + dlat / 2)), Y(max(south, la - dlat / 2))
            fill = ramp((v - lo) / (hi - lo)) if v is not None and math.isfinite(v) else "#e5e7eb"
            out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0 + 0.4:.1f}" height="{y1 - y0 + 0.4:.1f}" fill="{fill}"/>')
    # graticule
    for la in nice_ticks(south, north, 4):
        if south <= la <= north:
            out.append(f'<line x1="{ml}" y1="{Y(la):.1f}" x2="{ml + pw}" y2="{Y(la):.1f}" stroke="#ffffff" stroke-opacity="0.55" stroke-width="0.6"/>')
            out.append(_t(ml - 6, Y(la) + 3.5, f"{la:.1f}°N", anchor="end", size=9))
    for lo_ in nice_ticks(west, east, 4):
        if west <= lo_ <= east:
            out.append(f'<line x1="{X(lo_):.1f}" y1="{mt}" x2="{X(lo_):.1f}" y2="{mt + ph:.1f}" stroke="#ffffff" stroke-opacity="0.55" stroke-width="0.6"/>')
            out.append(_t(X(lo_), mt + ph + 14, f"{lo_:.1f}°E", anchor="middle", size=9))
    out.append(f'<rect x="{ml}" y="{mt}" width="{pw}" height="{ph:.1f}" fill="none" stroke="{MUTED}" stroke-width="0.8"/>')
    ref_speed = None
    if arrows:
        alats, alons, u, v = arrows
        speeds = [math.hypot(u[r][c], v[r][c]) for r in range(len(alats)) for c in range(len(alons)) if u[r][c] is not None and v[r][c] is not None]
        if speeds:
            ref_speed = max(1.0, round(sorted(speeds)[int(0.9 * (len(speeds) - 1))]))
            cell = pw / max(1, len(alons) - 1)
            scale = cell * 0.9 / ref_speed
            for r, la in enumerate(alats):
                for c, lo_ in enumerate(alons):
                    uu, vv = u[r][c], v[r][c]
                    if uu is None or vv is None:
                        continue
                    sp = math.hypot(uu, vv)
                    if sp < 0.05:
                        continue
                    ln = min(sp * scale, cell * 1.0)
                    ang = math.atan2(-vv, uu)  # screen y points down
                    cx, cy = X(lo_), Y(la)
                    x1, y1 = cx - math.cos(ang) * ln / 2, cy - math.sin(ang) * ln / 2
                    x2, y2 = cx + math.cos(ang) * ln / 2, cy + math.sin(ang) * ln / 2
                    if min(x1, x2) < ml or max(x1, x2) > ml + pw or min(y1, y2) < mt or max(y1, y2) > mt + ph:
                        continue  # an arrow that would leave the frame is left out, not clipped to a different direction
                    hl = min(5.0, ln * 0.45)
                    a1, a2 = ang + math.radians(150), ang - math.radians(150)
                    out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{INK}" stroke-width="1.1"/>')
                    out.append(f'<polygon points="{x2:.1f},{y2:.1f} {x2 + math.cos(a1) * hl:.1f},{y2 + math.sin(a1) * hl:.1f} {x2 + math.cos(a2) * hl:.1f},{y2 + math.sin(a2) * hl:.1f}" fill="{INK}"/>')
    for la, lo_, v, label in points or []:
        if not (south <= la <= north and west <= lo_ <= east):
            continue
        fill = ramp((v - lo) / (hi - lo)) if v is not None and math.isfinite(v) else "#ffffff"
        out.append(f'<circle cx="{X(lo_):.1f}" cy="{Y(la):.1f}" r="4.2" fill="{fill}" stroke="{INK}" stroke-width="1.1"/>')
    if marker:
        la, lo_, name = marker
        x, y = X(lo_), Y(la)
        out.append(f'<polygon points="{x:.1f},{y - 8:.1f} {x + 5:.1f},{y:.1f} {x:.1f},{y + 8:.1f} {x - 5:.1f},{y:.1f}" fill="#ffffff" stroke="{INK}" stroke-width="1.4"/>')
        out.append(_t(x + 9, y + 4, name, size=10, fill=INK, weight="bold"))
    # colour bar
    bx, bt, bh = width - mr + 22, mt, min(ph, 150.0)
    steps = 30
    for k in range(steps):
        t = 1 - k / (steps - 1)
        out.append(f'<rect x="{bx}" y="{bt + bh * k / steps:.1f}" width="12" height="{bh / steps + 0.5:.1f}" fill="{ramp(t)}"/>')
    out.append(f'<rect x="{bx}" y="{bt}" width="12" height="{bh}" fill="none" stroke="{MUTED}" stroke-width="0.6"/>')
    for tv in nice_ticks(lo, hi, 4):
        if lo <= tv <= hi:
            yy = bt + bh * (1 - (tv - lo) / (hi - lo))
            out.append(f'<line x1="{bx + 12}" y1="{yy:.1f}" x2="{bx + 16}" y2="{yy:.1f}" stroke="{MUTED}" stroke-width="0.6"/>')
            out.append(_t(bx + 19, yy + 3.5, fmt(tv), size=9))
    out.append(_t(bx, bt + bh + 16, unit, size=9, fill=INK))
    note = f"Cells coloured on this field's own range {fmt(lo)} to {fmt(hi)} {unit}" if vmin is None else f"Colour scale {fmt(lo)} to {fmt(hi)} {unit}"
    if ref_speed is not None:
        note += f"; arrows point where the air goes, a full cell spacing is {ref_speed:g} {arrow_unit}"
    out.append(_t(ml, height - 10, note, size=8.5))
    return _svg(width, height, "".join(out))


# ---- skill bars -----------------------------------------------------------------------------------------------------
def skill_chart(rows: list[tuple[str, float, float | None, float | None, float | None]], *, width: int = 720, xlabel: str = "skill") -> str:
    """Rows of (label, median, p25, p75, share_positive). Zero is 'no better than the baseline'; right of it is better."""
    if not rows:
        return _svg(width, 60, _t(width / 2, 34, "No evaluation results", anchor="middle", size=12))
    row = 22
    ml, mr, mt, mb = 200, 90, 10, 40
    height = mt + row * len(rows) + mb
    pw = width - ml - mr
    lo = min(-0.25, min((r[2] if r[2] is not None else r[1]) for r in rows) - 0.05)
    hi = max(0.25, max((r[3] if r[3] is not None else r[1]) for r in rows) + 0.05)

    def X(v: float) -> float:
        return ml + pw * (v - lo) / (hi - lo)

    out = []
    for tv in nice_ticks(lo, hi, 6):
        if lo <= tv <= hi:
            out.append(f'<line x1="{X(tv):.1f}" y1="{mt}" x2="{X(tv):.1f}" y2="{mt + row * len(rows)}" stroke="{GRID}" stroke-width="0.6"/>')
            out.append(_t(X(tv), mt + row * len(rows) + 14, fmt(tv), anchor="middle", size=9))
    out.append(f'<line x1="{X(0):.1f}" y1="{mt}" x2="{X(0):.1f}" y2="{mt + row * len(rows)}" stroke="{INK}" stroke-width="1.2"/>')
    for k, (label, med, p25, p75, share) in enumerate(rows):
        y = mt + k * row
        colour = "#059669" if med > 0 else "#dc2626"
        x0, x1 = sorted((X(0), X(med)))
        out.append(_t(ml - 8, y + 14, label, anchor="end", size=9.5, fill=INK))
        out.append(f'<rect x="{x0:.1f}" y="{y + 4}" width="{max(1.0, x1 - x0):.1f}" height="{row - 9}" fill="{colour}" fill-opacity="0.85"/>')
        if p25 is not None and p75 is not None:
            out.append(f'<line x1="{X(p25):.1f}" y1="{y + row / 2:.1f}" x2="{X(p75):.1f}" y2="{y + row / 2:.1f}" stroke="{INK}" stroke-width="1"/>')
        if share is not None:
            out.append(_t(width - mr + 10, y + 14, f"{share * 100:.0f}% of windows", size=8.5))
    out.append(_t(ml, height - 8, f"{xlabel}: right of the line is closer to the observations than the baseline; the thin line spans the middle half of the windows.", size=8.5))
    return _svg(width, height, "".join(out))
