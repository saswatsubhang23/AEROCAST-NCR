"""Real terrain and imagery for the Delhi-NCR domain, registered to latitude/longitude.

What this serves, exactly:
  * a height map: elevation in metres from the AWS/Mapzen "Terrarium" terrain tiles (a mosaic of SRTM, ASTER and other public DEMs),
    resampled to a regular latitude/longitude grid;
  * an image: the Sentinel-2 cloudless composite (EOX, 2020) resampled to the same regular latitude/longitude frame.

Both are *static reference layers*. The imagery is a cloud-free yearly composite, NOT today's satellite view, and the application says so.
Resampling is bilinear and only reprojects (Web-Mercator tiles to an equirectangular frame so the 3D scene, whose x is proportional to
longitude and z to latitude, is registered to the ground without a hidden distortion). Nothing is invented: if a tile cannot be fetched
the whole product is unavailable rather than partly filled.
"""

from __future__ import annotations

import asyncio
import base64
import io
import math
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

TILE = 256
# Same box as the weather lattice and the 3D scene frame, so every layer shares one registration.
SOUTH, NORTH, WEST, EAST = 28.1, 29.05, 76.7, 77.8

DEM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
IMAGERY_URL = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg"

DEM_ZOOM = 10  # about 150 m per pixel at this latitude
IMAGERY_ZOOM = 12  # about 33 m per pixel
IMAGERY_WIDTH = 2048
HEIGHT_STEP_DEG = 0.004  # about 440 m (lat) x 390 m (lon) between height samples

SOURCES = {
    "dem": {
        "name": "Terrain tiles (Terrarium)",
        "provider": "Mapzen / Amazon Web Services Open Data",
        "composition": "SRTM, ASTER GDEM, NED, GMTED and other public elevation datasets",
        "attribution": "Terrain Tiles © Mapzen, AWS Open Data; contains SRTM, ASTER and other public DEMs",
        "nominal_resolution_m": 150,
    },
    "imagery": {
        "name": "Sentinel-2 cloudless 2020",
        "provider": "EOX IT Services GmbH",
        "composition": "Cloud-free yearly composite of Copernicus Sentinel-2 scenes from 2020 (10 m source pixels)",
        "attribution": "Sentinel-2 cloudless — https://s2maps.eu by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2020)",
        "licence": "CC BY-NC-SA 4.0 (non-commercial)",
        "is_current": False,
    },
}


class TerrainUnavailable(Exception):
    """A tile source could not be reached or returned something that is not a tile."""


def tile_xy(lat: float, lon: float, z: int) -> tuple[float, float]:
    """Fractional Web-Mercator tile coordinates (x east, y south) of a point."""
    n = 2.0**z
    x = (lon + 180.0) / 360.0 * n
    r = math.radians(lat)
    y = (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n
    return x, y


def decode_terrarium(rgb: np.ndarray) -> np.ndarray:
    """Terrarium encoding: metres = (R * 256 + G + B / 256) - 32768."""
    a = rgb.astype(np.float32)
    return a[..., 0] * 256.0 + a[..., 1] + a[..., 2] / 256.0 - 32768.0


def _bilinear(src: np.ndarray, px: np.ndarray, py: np.ndarray) -> np.ndarray:
    """Sample `src` (H, W[, C]) at fractional pixel coordinates (px, py), clamped to the mosaic."""
    h, w = src.shape[:2]
    x = np.clip(px, 0, w - 1.0001)
    y = np.clip(py, 0, h - 1.0001)
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx = (x - x0).astype(np.float32)
    fy = (y - y0).astype(np.float32)
    if src.ndim == 3:
        fx = fx[..., None]
        fy = fy[..., None]
    a = src[y0, x0]
    b = src[y0, x0 + 1]
    c = src[y0 + 1, x0]
    d = src[y0 + 1, x0 + 1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


@dataclass(frozen=True)
class Mosaic:
    """Tiles of one zoom level stitched together; `x0`/`y0` are the tile indices of the top-left tile."""

    pixels: np.ndarray
    z: int
    x0: int
    y0: int

    def pixel_of(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        n = (2.0**self.z) * TILE
        px = (lon + 180.0) / 360.0 * n - self.x0 * TILE
        r = np.radians(lat)
        py = (1.0 - np.log(np.tan(r) + 1.0 / np.cos(r)) / np.pi) / 2.0 * n - self.y0 * TILE
        # tile centres: pixel i covers [i, i+1), so its sample point is i + 0.5
        return px - 0.5, py - 0.5


def tile_range(z: int, south: float = SOUTH, north: float = NORTH, west: float = WEST, east: float = EAST) -> tuple[int, int, int, int]:
    x_min, y_max = tile_xy(south, west, z)
    x_max, y_min = tile_xy(north, east, z)
    return int(math.floor(x_min)), int(math.floor(y_min)), int(math.floor(x_max)), int(math.floor(y_max))


class TerrainService:
    def __init__(self, cache_dir: str | Path, client: httpx.AsyncClient | None = None, dem_url: str = DEM_URL, imagery_url: str = IMAGERY_URL):
        self._dir = Path(cache_dir)
        self._client = client
        self._dem_url = dem_url
        self._imagery_url = imagery_url
        self._lock = asyncio.Lock()
        self._products: dict[str, object] = {}

    # ------------------------------------------------------------------ tiles
    async def _tile(self, client: httpx.AsyncClient, kind: str, template: str, z: int, x: int, y: int, ext: str) -> bytes:
        path = self._dir / "tiles" / kind / str(z) / str(x) / f"{y}.{ext}"
        if path.is_file() and path.stat().st_size > 0:
            return path.read_bytes()
        url = template.format(z=z, x=x, y=y)
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = await client.get(url, timeout=30.0)
                if r.status_code == 200 and r.content:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_suffix(path.suffix + ".part")
                    tmp.write_bytes(r.content)
                    tmp.replace(path)
                    return r.content
                last = TerrainUnavailable(f"{kind} tile {z}/{x}/{y} returned HTTP {r.status_code}")
            except httpx.HTTPError as exc:
                last = exc
            await asyncio.sleep(0.5 * (attempt + 1))
        raise TerrainUnavailable(f"{kind} tile {z}/{x}/{y} could not be fetched: {last}") from None

    async def _mosaic(self, kind: str, template: str, z: int, ext: str, mode: str) -> Mosaic:
        x0, y0, x1, y1 = tile_range(z)
        own = self._client is None
        client = self._client or httpx.AsyncClient(follow_redirects=True, headers={"User-Agent": "aerocast-ncr/0.1 (terrain reference layers)"})
        sem = asyncio.Semaphore(8)

        async def one(x: int, y: int) -> tuple[int, int, bytes]:
            async with sem:
                return x, y, await self._tile(client, kind, template, z, x, y, ext)

        try:
            got = await asyncio.gather(*[one(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)])
        finally:
            if own:
                await client.aclose()
        channels = 3
        canvas = np.zeros(((y1 - y0 + 1) * TILE, (x1 - x0 + 1) * TILE, channels), dtype=np.uint8)
        for x, y, data in got:
            try:
                img = Image.open(io.BytesIO(data)).convert(mode)
            except Exception as exc:  # noqa: BLE001 - any decode failure means the tile is not a usable image
                raise TerrainUnavailable(f"{kind} tile {z}/{x}/{y} is not a valid image") from exc
            if img.size != (TILE, TILE):
                raise TerrainUnavailable(f"{kind} tile {z}/{x}/{y} has size {img.size}, expected {TILE}x{TILE}")
            canvas[(y - y0) * TILE:(y - y0 + 1) * TILE, (x - x0) * TILE:(x - x0 + 1) * TILE] = np.asarray(img)
        return Mosaic(canvas, z, x0, y0)

    # ------------------------------------------------------------------ products
    @staticmethod
    def height_axes() -> tuple[np.ndarray, np.ndarray]:
        rows = int(round((NORTH - SOUTH) / HEIGHT_STEP_DEG)) + 1
        cols = int(round((EAST - WEST) / HEIGHT_STEP_DEG)) + 1
        return np.linspace(SOUTH, NORTH, rows), np.linspace(WEST, EAST, cols)

    async def heightmap(self) -> dict:
        async with self._lock:
            if "height" in self._products:
                return self._products["height"]  # type: ignore[return-value]
            m = await self._mosaic("terrarium", self._dem_url, DEM_ZOOM, "png", "RGB")
            elev = decode_terrarium(m.pixels)
            lats, lons = self.height_axes()
            la, lo = np.meshgrid(lats, lons, indexing="ij")
            px, py = m.pixel_of(la, lo)
            h = _bilinear(elev, px, py)
            if not np.isfinite(h).all() or h.min() < -500 or h.max() > 9000:
                raise TerrainUnavailable("the elevation tiles decoded to implausible values")
            q = np.rint(h).astype("<i2")  # whole metres; row 0 is the southernmost row (same convention as the weather lattice)
            out = {
                "rows": int(len(lats)),
                "cols": int(len(lons)),
                "bounds": {"south": SOUTH, "north": NORTH, "west": WEST, "east": EAST},
                "lats": [round(float(v), 5) for v in (lats[0], lats[-1])],
                "lons": [round(float(v), 5) for v in (lons[0], lons[-1])],
                "spacing_deg": HEIGHT_STEP_DEG,
                "unit": "m",
                "datum": "above mean sea level (EGM96 geoid as used by SRTM)",
                "encoding": "int16-le-base64",
                "row_order": "south-to-north",
                "min_m": int(q.min()),
                "max_m": int(q.max()),
                "heights": base64.b64encode(q.tobytes()).decode("ascii"),
                "source": SOURCES["dem"],
                "resampling": "bilinear from Web-Mercator tiles (zoom %d) to a regular latitude/longitude grid" % DEM_ZOOM,
            }
            self._products["height"] = out
            return out

    def imagery_frame(self) -> tuple[int, int]:
        km_lat = (NORTH - SOUTH) * 111.32
        km_lon = (EAST - WEST) * 111.32 * math.cos(math.radians((NORTH + SOUTH) / 2))
        return IMAGERY_WIDTH, int(round(IMAGERY_WIDTH * km_lat / km_lon))

    async def imagery(self) -> bytes:
        async with self._lock:
            if "imagery" in self._products:
                return self._products["imagery"]  # type: ignore[return-value]
            path = self._dir / "imagery-domain.jpg"
            if path.is_file() and path.stat().st_size > 0:
                self._products["imagery"] = path.read_bytes()
                return self._products["imagery"]  # type: ignore[return-value]
            m = await self._mosaic("s2cloudless-2020", self._imagery_url, IMAGERY_ZOOM, "jpg", "RGB")
            w, h = self.imagery_frame()
            lons = WEST + (EAST - WEST) * (np.arange(w) + 0.5) / w
            lats = NORTH - (NORTH - SOUTH) * (np.arange(h) + 0.5) / h  # image row 0 is the north edge
            la, lo = np.meshgrid(lats, lons, indexing="ij")
            px, py = m.pixel_of(la, lo)
            rgb = np.clip(np.rint(_bilinear(m.pixels.astype(np.float32), px, py)), 0, 255).astype(np.uint8)
            buf = io.BytesIO()
            Image.fromarray(rgb, "RGB").save(buf, "JPEG", quality=88, optimize=True)
            data = buf.getvalue()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self._products["imagery"] = data
            return data

    def meta(self) -> dict:
        w, h = self.imagery_frame()
        rows, cols = self.height_axes()
        return {
            "bounds": {"south": SOUTH, "north": NORTH, "west": WEST, "east": EAST},
            "heightmap": {"rows": len(rows), "cols": len(cols), "spacing_deg": HEIGHT_STEP_DEG, "source": SOURCES["dem"]},
            "imagery": {"width": w, "height": h, "source": SOURCES["imagery"], "frame": "regular latitude/longitude; row 0 is the north edge"},
            "notes": [
                "Terrain and imagery are static reference layers, not live observations.",
                "The imagery is a cloud-free 2020 composite and does not show today's clouds, smoke or haze.",
                "Elevation is exaggerated on screen in the 3D view; the factor is shown there.",
            ],
        }
