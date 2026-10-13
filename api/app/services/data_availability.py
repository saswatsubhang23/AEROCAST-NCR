"""What data the application has, what it only has partly, and what it does not have at all, with the consequence of each gap.

Live facts are computed from the running system (the historical store, the provider probes, the trained model, the keys that are set).
The catalogue of things the application does NOT have is written down, because absence cannot be probed: for each it says what it would
unlock and where it could come from. Nothing here claims data that is not on disk or reachable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings

# available  in the application and current
# partial    in the application with a stated limit
# stale      in the application but out of date
# obtainable not in the application, but a free public source exists (often one this application already uses)
# missing    not in the application and no free public source is known
Status = str


def _hours_since(iso_ts: str | None, now: datetime) -> float | None:
    if not iso_ts:
        return None
    try:
        t = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((now - t).total_seconds() / 3600.0, 1)


def _item(id_: str, name: str, status: Status, *, source: str, detail: str, used_for: str, consequence: str = "", how_to_get: str = "", evidence: str = "") -> dict:
    return {"id": id_, "name": name, "status": status, "source": source, "detail": detail, "used_for": used_for, "consequence": consequence, "how_to_get": how_to_get, "evidence": evidence}


def build_availability(settings: Settings, twin_status: dict | None, deps: dict[str, dict], model: dict | None, terrain_cached: bool, kb_documents: int | None,
                       now: datetime | None = None) -> dict:
    """`deps` maps dependency key -> {state, detail} from the system status; `twin_status` is TwinService.status() or None when the store is missing."""
    now = now or datetime.now(timezone.utc)
    groups: list[dict] = []

    # ------------------------------------------------------------------ air-quality observations
    air: list[dict] = []
    if twin_status:
        periods = twin_status.get("periods", {})
        for pol, label in (("pm25", "PM2.5"), ("pm10", "PM10"), ("no2", "NO2"), ("o3", "O3"), ("so2", "SO2")):
            p = periods.get(pol)
            if not p:
                air.append(_item(f"obs_{pol}", f"{label} station observations", "missing", source="historical store", detail="No usable hours are stored.",
                                 used_for="maps, simulation initial state, model features"))
                continue
            age = _hours_since(p.get("dense_to") or p.get("to"), now)
            stale = age is not None and age > 6
            air.append(_item(
                f"obs_{pol}", f"{label} station observations", "stale" if stale else "available", source="OpenAQ v3 + CPCB archive (xKDR), cleaned hourly store",
                detail=f"{p['from'][:10]} to {p['to'][:10]}; newest well-covered hour {(p.get('dense_to') or p['to'])[:16]}Z"
                       + (f", {age:.0f} h ago" if age is not None else "") + f"; about {twin_status.get('stations', '?')} stations.",
                used_for="Stations lens, spatial estimate, simulation start, the trained model's inputs",
                consequence=("The newest stored hour is old, so every map built from observations is a replay, and live forecasts are refused (inputs older than the 6 h limit)." if stale else ""),
                how_to_get="Refresh the feed from the Model Training page (download newest hours), or use the live OpenAQ endpoints.",
                evidence=f"{twin_status.get('stations', '?')} stations in the store",
            ))
    else:
        air.append(_item("obs_store", "Historical station store", "missing", source="api/data/history.sqlite", detail="The store is missing or empty.",
                         used_for="almost every twin feature", how_to_get="python -m app.history all"))
    aq = deps.get("aq_provider", {})
    air.append(_item(
        "live_openaq", "Live OpenAQ feed", "available" if aq.get("state") == "ok" else "missing" if aq.get("state") == "not_configured" else "partial",
        source="OpenAQ v3 (key AQ_API_KEY)", detail=aq.get("detail", "unknown"),
        used_for="Air Quality page, alerts, reports, 'download newest hours'",
        consequence="Many stations publish with a lag of days, so 'live' is rarely the last hour.",
        how_to_get="Free key at explore.openaq.org/register, set AQ_API_KEY in api/.env.",
    ))
    air.append(_item("obs_co", "CO observations", "missing", source="stored sensors", detail="All CO sensors in the window are labelled ppb with a median near 1: physically impossible, so they are excluded (UNIT_SUSPECT).",
                     used_for="would give a combustion tracer", consequence="No CO in any map, model or coupled run.", how_to_get="Re-ingest CPCB CO with confirmed units (mg/m3)."))
    air.append(_item("obs_nox", "NO and NOx observations", "obtainable", source="OpenAQ v3 (parameters 'no' and 'nox', ppb), CPCB stations",
                     detail="Offered by the OpenAQ feed this application already uses (seen in the 2026-10-11 audit) but not ingested, so every model and map works without them.",
                     used_for="NO titration of O3, NOx as a combustion tracer", consequence="O3 and NO2 cannot be coupled chemically; Ox = O3 + NO2 is used instead.",
                     how_to_get="Add 'no' and 'nox' to the ingest parameter list (units ppb are already handled by the unit converter)."))
    air.append(_item("obs_nh3_voc", "NH3 and VOC observations", "missing", source="-", detail="Not offered by any feed used here.",
                     used_for="nitrate formation, secondary organic aerosol", consequence="No nitrate or secondary organic aerosol in any model.", how_to_get="Research campaigns only."))
    air.append(_item("speciation", "PM chemical speciation (sulfate, nitrate, OC, EC, dust)", "missing", source="-", detail="Only total PM2.5 and PM10 mass are observed.",
                     used_for="source attribution, secondary aerosol", consequence="The model cannot tell dust from smoke from sulfate; SO2 -> sulfate is a mass-conversion assumption.",
                     how_to_get="CPCB manual speciation campaigns, or SAFAR; not a free live feed."))
    air.append(_item("vertical_pollutants", "Vertical profile of pollutants (lidar, sondes, tall-tower)", "missing", source="-", detail="All concentrations are at ground level.",
                     used_for="3D concentration fields, mixed-layer validation", consequence="The 3D view shows no measured concentration above ground; any layer drawn in 3D is labelled illustrative.",
                     how_to_get="ceilometer/lidar networks (e.g. IITM), research campaigns."))
    air.append(_item("satellite_air", "Satellite AOD and NO2 columns", "obtainable", source="NASA MODIS/VIIRS AOD, Copernicus Sentinel-5P TROPOMI (free accounts)", detail="Not ingested. CAMS gives a modelled AOD only.",
                     used_for="regional haze, transport from outside the domain, spatial gaps between stations", consequence="Air entering the domain is 'unknown'; no observed regional field fills the gaps between stations.",
                     how_to_get="MODIS/VIIRS AOD (NASA LAADS, free account), Sentinel-5P TROPOMI NO2 (Copernicus)."))
    groups.append({"key": "air", "label": "Air-quality observations", "items": air})

    # ------------------------------------------------------------------ meteorology
    wx: list[dict] = []
    wp = deps.get("weather_provider", {})
    wx.append(_item(
        "wx_surface", "Weather-model fields (temperature, humidity, pressure, rain, cloud, boundary-layer height, radiation, visibility)",
        "available" if wp.get("state") == "ok" else "partial", source="Open-Meteo (ECMWF IFS), free non-commercial tier",
        detail=f"{wp.get('detail', 'unknown')}. Native cells about 0.07 x 0.10 degrees (8 x 10 km), hourly, past days and 3 days ahead.",
        used_for="Atmosphere lens, wind particles, transport and coupled simulation, 3D scene", consequence="They are model values: sharper than the grid they come from they are not.",
        how_to_get="Already connected. A commercial plan is needed for commercial use."))
    wx.append(_item("wx_levels", "Winds aloft (80, 120, 180 m and 925, 850, 700 hPa)", "available" if wp.get("state") == "ok" else "partial", source="Open-Meteo (model output)",
                    detail="Seven model levels from 10 m to about 3 km, with their geopotential heights.", used_for="3D wind flow with real vertical structure",
                    consequence="Between those levels the 3D flow is interpolated, not resolved; there is no vertical wind (w) in the displayed flow.", how_to_get="Already connected (levels=true)."))
    wx.append(_item("wx_observed", "Observed meteorology at the stations (temperature, humidity, wind speed and direction)", "obtainable", source="OpenAQ v3 (CPCB stations report them), IMD",
                    detail="OpenAQ lists temperature, relative humidity, wind speed and wind direction sensors on CPCB stations (2026-10-11 audit). They are not ingested: every weather value in the application is model output.",
                    used_for="verifying the model wind and boundary-layer depth, a measured wind at the stations", consequence="Errors of the model wind propagate into every transport result, unquantified.",
                    how_to_get="Ingest the OpenAQ meteorological parameters; radiosondes for Safdarjung from the University of Wyoming archive (free) for the vertical structure."))
    wx.append(_item("wx_nowcast", "Radar and live satellite cloud/rain imagery", "missing", source="-", detail="Rain and cloud are model forecasts; the Sentinel-2 background is a 2020 composite.",
                    used_for="current rain, cloud and smoke/haze", consequence="The picture cannot show what is in the sky right now.", how_to_get="IMD radar products, INSAT-3D/3DR, EUMETSAT/Himawari."))
    wx.append(_item("wx_hires", "High-resolution regional weather model (WRF, ICON-D2) for NCR", "missing", source="-", detail="Best available resolution here is about 8-10 km.",
                    used_for="urban-scale flow, sea-breeze-like and valley effects, street-level exposure", consequence="Wind features smaller than ~10 km, the Aravalli ridge's flow effects and city heat-island circulation are not resolved.",
                    how_to_get="Run WRF locally (needs boundary data and compute), or a commercial high-resolution provider."))
    wx.append(_item("terrain_imagery", "Terrain and satellite imagery", "available" if terrain_cached else "partial", source="Terrarium DEM (SRTM-based) + Sentinel-2 cloudless 2020",
                    detail="Cached on this machine." if terrain_cached else "Built on first use of the 3D view (about 30 s, then cached).",
                    used_for="3D ground, basemap", consequence="Static: not today's imagery.", how_to_get="Already connected."))
    groups.append({"key": "met", "label": "Meteorology and geography", "items": wx})

    # ------------------------------------------------------------------ sources and drivers
    src = [
        _item("emissions", "Emission inventory (traffic, industry, power, residential, construction)", "obtainable", source="-", detail="No source term exists anywhere in the application.",
              used_for="forecasting concentration changes that are not transport or removal", consequence="No model here can create pollution: forecasts are carried-air forecasts or statistical (ML) forecasts. This is the largest gap.",
              how_to_get="EDGAR / SAFAR-India / TERI-IITK inventories (gridded, annual), diurnal profiles from traffic data."),
        _item("fires", "Fire and stubble-burning detections", "obtainable", source="NASA FIRMS (VIIRS/MODIS active fires), free MAP_KEY", detail="Not ingested.", used_for="the autumn smoke episodes that dominate Delhi PM2.5",
              consequence="The model cannot know about upwind smoke before it arrives at a station.", how_to_get="NASA FIRMS active-fire (VIIRS/MODIS): free MAP_KEY."),
        _item("traffic", "Traffic counts and congestion", "missing", source="-", detail="Not available.", used_for="diurnal emission shape", consequence="Morning/evening peaks are not represented.",
              how_to_get="City traffic authorities, TomTom/HERE (commercial)."),
        _item("landuse", "Land use, population density and building height", "obtainable", source="ESA WorldCover, WorldPop, GHSL (free)", detail="Not loaded. The exposure tables exist in the schema and are empty.", used_for="exposure, urban roughness, deposition surface types",
              consequence="Deposition velocity is one value per species; exposure cannot be population-weighted.", how_to_get="ESA WorldCover, WorldPop, GHSL (all free)."),
    ]
    groups.append({"key": "sources", "label": "Sources and drivers", "items": src})

    # ------------------------------------------------------------------ models
    mdl: list[dict] = []
    if model and model.get("available"):
        age = _hours_since(model.get("created_at"), now)
        mdl.append(_item("ml_model", "Trained pollutant forecast model", "available", source="local training run " + str(model.get("run_id")),
                         detail=f"PM2.5, PM10, NO2, O3 at +1, +6, +24 h; trained {str(model.get('created_at'))[:10]}" + (f" ({age/24:.0f} days ago)" if age is not None else "") + ".",
                         used_for="Model forecast tab, early warning, model-forecast-initialised coupled runs",
                         consequence="SO2, CO and the +3/+12/+48/+72 h horizons have no model. PM10 +24 h does not beat persistence.",
                         how_to_get="Train from the Model Training page (it is your button; nothing trains automatically)."))
    else:
        mdl.append(_item("ml_model", "Trained pollutant forecast model", "missing", source="api/data/models", detail=(model or {}).get("reason", "No model is configured."),
                         used_for="Model forecast, early warning", consequence="Pollutant forecasts are unavailable; the physical simulations still run.", how_to_get="Train from the Model Training page."))
    cams = deps.get("weather_provider", {}).get("state") == "ok"
    mdl.append(_item("cams", "CAMS chemistry-transport model fields (via Open-Meteo)", "available" if cams else "partial", source="Open-Meteo air-quality API (ECMWF CAMS)",
                     detail="PM2.5, PM10, NO2, SO2, O3, CO, NO, AOD, dust in cells of about 0.4 degrees (44 km: about 3 x 3 cells over NCR); model, not measurement.", used_for="the Model air panel; an independent reference to compare with",
                     consequence="Very coarse (about 44 km cells) and not assimilated with the stations here; it can differ strongly from them and shows no city-scale structure.", how_to_get="Already connected."))
    mdl.append(_item("coupled", "Coupled multi-species transport model", "available", source="AEROCAST (reduced form, no training)",
                     detail="Five species with ventilation, deposition, wet scavenging and SO2 -> sulfate.", used_for="Coupled simulation lens",
                     consequence="Not validated as a chemistry-transport model and has no emissions; the app shows its hindcast against persistence and passive transport.",
                     how_to_get="Built in. See docs/coupled-evaluation.md."))
    llm = deps.get("llm_model", {})
    mdl.append(_item("llm", "Language model for the assistant", "available" if llm.get("state") == "ok" else "partial" if llm.get("state") == "degraded" else "missing",
                     source=f"Ollama, {settings.ollama_model}", detail=llm.get("detail", "unknown"), used_for="Assistant, report summaries",
                     consequence="Without it the assistant and summaries report themselves unavailable.", how_to_get=f"ollama pull {settings.ollama_model}"))
    mdl.append(_item("kb", "Evidence documents (knowledge base)", "partial" if kb_documents else "missing", source="local Chroma index",
                     detail=f"{kb_documents} document(s) indexed." if kb_documents else "No documents are indexed.", used_for="grounded assistant answers, report citations",
                     consequence="Answers cannot cite guidelines or studies you have not added.", how_to_get="Upload PDFs/text on the Knowledge Base page."))
    groups.append({"key": "models", "label": "Models and knowledge", "items": mdl})

    # ------------------------------------------------------------------ health
    groups.append({"key": "health", "label": "Health and exposure", "items": [
        _item("health_data", "Patient-level or hospital-admission data", "missing", source="-", detail="None provided; the exposure UI waits for it.",
              used_for="exposure-response analysis", consequence="The application reports air quality, not health outcomes.", how_to_get="Provided by you, under a data-handling policy."),
    ]})

    counts = {k: sum(1 for g in groups for i in g["items"] if i["status"] == k) for k in ("available", "partial", "stale", "obtainable", "missing")}
    return {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "counts": counts, "groups": groups,
            "principle": "A gap is shown as a gap. Where data are missing the application says so and does not substitute invented or synthetic values."}


def terrain_cached(settings: Settings) -> bool:
    return (Path(settings.data_dir) / "terrain" / "imagery-domain.jpg").is_file()
