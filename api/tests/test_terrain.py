"""Terrain and imagery registration. A fake tile server encodes each pixel's own longitude/latitude in its value, so a flipped axis,
an offset or a Mercator/equirectangular mix-up shows up as a wrong number at a known place. No network is used."""

import base64
import io
import math

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.terrain import service as ts

Z_DEM, Z_IMG = ts.DEM_ZOOM, ts.IMAGERY_ZOOM


def pixel_lonlat(z: int, x: int, y: int) -> tuple[np.ndarray, np.ndarray]:
    """Longitude and latitude of every pixel centre of tile (z, x, y); arrays are (256, 256) indexed [row, col]."""
    n = 256 * 2**z
    cols = (x * 256 + np.arange(256) + 0.5) / n
    rows = (y * 256 + np.arange(256) + 0.5) / n
    lon = cols * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * rows))))
    return np.broadcast_to(lon[None, :], (256, 256)), np.broadcast_to(lat[:, None], (256, 256))


def elevation_of(lon, lat):
    """A known ground: 300 m + 1000 m per degree east of 77 + 500 m per degree north of 28.5."""
    return 300.0 + (lon - 77.0) * 1000.0 + (lat - 28.5) * 500.0


def png_terrarium(x: int, y: int, z: int) -> bytes:
    lon, lat = pixel_lonlat(z, x, y)
    v = elevation_of(lon, lat) + 32768.0
    whole = np.floor(v)
    rgb = np.stack([np.floor(whole / 256), whole % 256, np.floor((v - whole) * 256)], axis=-1).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, "PNG")
    return buf.getvalue()


def jpg_marker(x: int, y: int, z: int) -> bytes:
    """Red encodes the longitude fraction of the domain, green the latitude fraction (0 at the south edge)."""
    lon, lat = pixel_lonlat(z, x, y)
    r = np.clip((lon - ts.WEST) / (ts.EAST - ts.WEST), 0, 1) * 255
    g = np.clip((lat - ts.SOUTH) / (ts.NORTH - ts.SOUTH), 0, 1) * 255
    rgb = np.stack([r, g, np.full_like(r, 128)], axis=-1).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, "JPEG", quality=95, subsampling=0)
    return buf.getvalue()


def fake_server(requests: list[str] | None = None, fail: bool = False) -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(str(req.url))
        if fail:
            return httpx.Response(500)
        path = req.url.path
        if "terrarium" in path:
            z, x, y = (int(p.removesuffix(".png")) for p in path.rsplit("/", 3)[-3:])
            return httpx.Response(200, content=png_terrarium(x, y, z))
        # imagery template is .../{z}/{y}/{x}.jpg
        z, y, x = (int(p.removesuffix(".jpg")) for p in path.rsplit("/", 3)[-3:])
        return httpx.Response(200, content=jpg_marker(x, y, z))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def service(tmp_path, **kw) -> ts.TerrainService:
    return ts.TerrainService(tmp_path, client=fake_server(**kw))


# ---------------------------------------------------------------------------------------------------- pure helpers
def test_tile_math_matches_known_tile():
    # Delhi (28.61 N, 77.20 E) is in tile 10/731/427, verified against the live tile server during development.
    x, y = ts.tile_xy(28.61, 77.20, 10)
    assert (math.floor(x), math.floor(y)) == (731, 427)


def test_terrarium_decoding_round_trips():
    for metres in (-10.5, 0.0, 215.25, 718.0, 4000.75):
        v = metres + 32768.0
        whole = math.floor(v)
        rgb = np.array([[[whole // 256, whole % 256, int((v - whole) * 256)]]], dtype=np.uint8)
        assert abs(float(ts.decode_terrarium(rgb)[0, 0]) - metres) < 0.01


# ---------------------------------------------------------------------------------------------------- height map registration
@pytest.mark.asyncio
async def test_heightmap_is_registered_to_latitude_and_longitude(tmp_path):
    out = await service(tmp_path).heightmap()
    rows, cols = out["rows"], out["cols"]
    h = np.frombuffer(base64.b64decode(out["heights"]), dtype="<i2").reshape(rows, cols)
    lats, lons = ts.TerrainService.height_axes()
    assert out["row_order"] == "south-to-north" and len(lats) == rows and len(lons) == cols
    # every sample equals the known ground at its own coordinates (to the 1 m the product is rounded to, plus Mercator sampling error)
    la, lo = np.meshgrid(lats, lons, indexing="ij")
    err = np.abs(h.astype(float) - elevation_of(lo, la))
    assert err.max() < 3.0
    # orientation: elevation rises east and rises north in the fake ground; row 0 is the south edge, column 0 the west edge
    assert h[0, 0] < h[0, -1] and h[0, 0] < h[-1, 0]
    assert out["min_m"] == int(h.min()) and out["max_m"] == int(h.max())
    assert out["source"]["attribution"]


@pytest.mark.asyncio
async def test_height_samples_are_cached_in_memory_and_tiles_on_disk(tmp_path):
    seen: list[str] = []
    svc = service(tmp_path, requests=seen)
    await svc.heightmap()
    first = len(seen)
    assert first > 0
    await svc.heightmap()
    assert len(seen) == first  # second call: no network
    # a fresh service re-reads the disk tile cache and does not touch the network
    seen2: list[str] = []
    fresh = ts.TerrainService(tmp_path, client=fake_server(requests=seen2))
    await fresh.heightmap()
    assert seen2 == []


# ---------------------------------------------------------------------------------------------------- imagery registration
@pytest.mark.asyncio
async def test_imagery_is_registered_and_north_is_the_top_row(tmp_path):
    data = await service(tmp_path).imagery()
    img = np.asarray(Image.open(io.BytesIO(data)).convert("RGB")).astype(float)
    w, h = ts.TerrainService(tmp_path).imagery_frame()
    assert img.shape == (h, w, 3)
    # red = longitude fraction (west to east), green = latitude fraction (south 0, north 1); row 0 is the north edge
    red_frac = img[:, :, 0] / 255.0
    green_frac = img[:, :, 1] / 255.0
    cols = (np.arange(w) + 0.5) / w
    rows_north_to_south = 1.0 - (np.arange(h) + 0.5) / h
    assert np.abs(red_frac - cols[None, :]).max() < 0.02
    assert np.abs(green_frac - rows_north_to_south[:, None]).max() < 0.02


@pytest.mark.asyncio
async def test_frame_has_the_metric_aspect_of_the_domain(tmp_path):
    w, h = ts.TerrainService(tmp_path).imagery_frame()
    km_lon = (ts.EAST - ts.WEST) * 111.32 * math.cos(math.radians((ts.NORTH + ts.SOUTH) / 2))
    km_lat = (ts.NORTH - ts.SOUTH) * 111.32
    assert abs(w / h - km_lon / km_lat) < 0.002


# ---------------------------------------------------------------------------------------------------- failure is honest
@pytest.mark.asyncio
async def test_unreachable_tiles_make_the_product_unavailable_not_partial(tmp_path, monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(ts.asyncio, "sleep", no_sleep)
    svc = ts.TerrainService(tmp_path, client=fake_server(fail=True))
    with pytest.raises(ts.TerrainUnavailable):
        await svc.heightmap()
    with pytest.raises(ts.TerrainUnavailable):
        await svc.imagery()


@pytest.mark.asyncio
async def test_a_non_image_response_is_rejected(tmp_path):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>not a tile</html>")))
    with pytest.raises(ts.TerrainUnavailable):
        await ts.TerrainService(tmp_path, client=client).heightmap()


# ---------------------------------------------------------------------------------------------------- HTTP surface
def test_endpoints(tmp_path, monkeypatch):
    from app.api import terrain as api_terrain
    from app.main import app

    svc = ts.TerrainService(tmp_path, client=fake_server())
    app.dependency_overrides.clear()
    monkeypatch.setattr(api_terrain, "get_terrain_service", lambda: svc)
    c = TestClient(app)
    meta = c.get("/api/terrain/meta").json()
    assert meta["bounds"]["south"] == ts.SOUTH and "is_current" in meta["imagery"]["source"] and meta["imagery"]["source"]["is_current"] is False
    hm = c.get("/api/terrain/heightmap")
    assert hm.status_code == 200 and hm.json()["encoding"] == "int16-le-base64"
    assert "max-age" in hm.headers["cache-control"]
    im = c.get("/api/terrain/imagery")
    assert im.status_code == 200 and im.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(im.content)).size == svc.imagery_frame()


def test_endpoint_reports_503_when_tiles_fail(tmp_path, monkeypatch):
    from app.api import terrain as api_terrain
    from app.main import app

    async def no_sleep(_):
        return None

    monkeypatch.setattr(ts.asyncio, "sleep", no_sleep)
    svc = ts.TerrainService(tmp_path, client=fake_server(fail=True))
    monkeypatch.setattr(api_terrain, "get_terrain_service", lambda: svc)
    r = TestClient(app).get("/api/terrain/heightmap")
    assert r.status_code == 503 and r.json()["error"]["code"] == "terrain_unavailable"
