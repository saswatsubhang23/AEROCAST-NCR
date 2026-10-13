# Terrain, imagery and georegistered fields (2026-10-11)

The 3D twin used to stand on a flat plane and the 2D map was a single dark vector basemap. Both now sit on real geography, and every data
field is registered to it by latitude and longitude. Nothing here is live data: terrain and imagery are **static reference layers**.

## What is shown, and where it comes from

| Layer | Source | Resolution | Is it current? |
|---|---|---|---|
| Terrain height | AWS/Mapzen "Terrarium" tiles (SRTM, ASTER and other public DEMs), zoom 10 | about 150 m source; served on a 0.004° (about 400 m) grid | static |
| Satellite imagery | Sentinel-2 cloudless 2020 (EOX IT Services), CC BY-NC-SA 4.0, zoom 12 | about 33 m source; 2048 px across the domain | **No.** A cloud-free 2020 composite: it does not show today's cloud, smoke or haze |
| Weather fields (precipitation, cloud, temperature, humidity, boundary layer, wind, pressure) | Open-Meteo model output | native model cells of about 0.07° x 0.10° (8 x 10 km); lattice 14 x 11 (was 8 x 9, which undersampled the model) | model forecast / analysis |
| Basemaps (2D) | CARTO Voyager and Dark (vector, with the project's CARTO key), Sentinel-2, terrain-shaded relief | - | static |

The coloured fields are model output drawn on top of the imagery. They are interpolated for display (bicubic, clamped to the surrounding
lattice values so no new extreme is invented); the model's own resolution is the limit, not the picture's.

## Registration (how a field lands on the ground it describes)

* Backend `api/app/terrain/service.py` fetches Web-Mercator tiles, mosaics them and **resamples to a regular latitude/longitude grid**
  over the same box as the weather lattice and the 3D frame (`28.10-29.05 N, 76.70-77.80 E`). The 3D scene's x is proportional to
  longitude and z to latitude, so the texture and the height map need no further correction.
* `GET /api/terrain/heightmap` (int16 metres, row 0 = south, base64), `GET /api/terrain/imagery` (JPEG, row 0 = north),
  `GET /api/terrain/meta` (bounds, sources, licences). Tiles are cached under `api/data/terrain/`; a tile that cannot be fetched makes the
  product **unavailable (503)**, never partially filled.
* Frontend `web/src/lib/terrain/terrain.ts`: `elevationAt` (bilinear, null outside the box), `terrainMesh`, and `drapeMesh`, which builds a
  mesh over any raster's bounds at least as fine as the terrain, lifted just above the ground, with UVs linear in longitude and
  Web-Mercator in latitude (how the rasters are generated). Station columns, rings, contours, the boundary-layer surface and the wind
  particles all take their base height from the same terrain.
* Tests prove registration, not only shape: `api/tests/test_terrain.py` feeds a tile server whose pixel values encode their own
  coordinates and checks every output sample (flipped or offset axes fail); `web/src/lib/terrain/terrain.test.ts` checks corner
  vertices, UVs, Mercator row spacing and face winding.

## Exaggeration (stated in the scene)

Atmosphere heights above ground are exaggerated x12 (unchanged); terrain relief is exaggerated x30 because the plain here varies by
only 145-383 m over 100 km. Both factors are drawn on the altitude axis and listed in "What is data and what is illustration".

## Visual style

* Rain is drawn like radar: a continuous violet-to-yellow colour blend between the legend's class colours with a feathered edge.
  Cloud cover is translucent white whose opacity follows the cover. Temperature, humidity and boundary-layer height blend between their
  class colours. The legend keeps the same class swatches.
* Basemap switch (Voyager / Dark / Satellite / Relief) is part of every MapLibre map (twin, weather, air quality, atmosphere); the
  choice is remembered in the browser. The Satellite basemap carries a note that it is a 2020 reference image.
* `ProvenanceBadge` has a new kind, **Reference layer**, for terrain and imagery.

## Configuration

`web/.env.local` holds `NEXT_PUBLIC_CARTO_API_KEY` (git-ignored; a template is `web/.env.example`). A tile key is necessarily visible in the
browser's tile requests, so restrict it to your own domains in the CARTO dashboard. Without a key the maps still load keyless.

## Limits

* The 2020 composite and static DEM do not change with time; there is no live satellite imagery, and no vertical concentration field.
* Open-Meteo's free tier is non-commercial and the lattice is 154 points per request (cached 30 minutes; historical 24 h).
* The 2D map is flat. The 3D view is where terrain is drawn; the deck.gl overlay of the 2D map does not follow terrain.
