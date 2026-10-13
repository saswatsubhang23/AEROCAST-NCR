from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from app.core.config import get_settings
from app.terrain.service import TerrainService, TerrainUnavailable

router = APIRouter(prefix="/terrain", tags=["terrain"])

_CACHE_CONTROL = "public, max-age=86400"


@lru_cache
def get_terrain_service() -> TerrainService:
    return TerrainService(Path(get_settings().data_dir) / "terrain")


def _unavailable(exc: TerrainUnavailable) -> HTTPException:
    return HTTPException(503, {"code": "terrain_unavailable", "message": f"Terrain data could not be built: {exc}"})


@router.get("/meta", summary="Bounds, sources and licences of the terrain and imagery layers")
def terrain_meta():
    return get_terrain_service().meta()


@router.get("/heightmap", summary="Elevation (m) on a regular latitude/longitude grid over Delhi-NCR")
async def terrain_heightmap(response: Response):
    try:
        out = await get_terrain_service().heightmap()
    except TerrainUnavailable as exc:
        raise _unavailable(exc) from exc
    response.headers["Cache-Control"] = _CACHE_CONTROL
    return out


@router.get("/imagery", summary="Sentinel-2 cloudless composite resampled to the same latitude/longitude frame")
async def terrain_imagery():
    try:
        data = await get_terrain_service().imagery()
    except TerrainUnavailable as exc:
        raise _unavailable(exc) from exc
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": _CACHE_CONTROL})
