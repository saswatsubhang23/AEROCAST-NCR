"""The transport engine alone: numerical behaviour, boundaries, parameters. No network, no store."""

import math

import numpy as np
import pytest

from app.twin.transport import Grid, MemberParams, regrid_bilinear, rotate_wind, run_transport

G = Grid(28.1, 29.05, 76.7, 77.8, 40, 40)
LAT, LON = np.meshgrid(G.lats, G.lons, indexing="ij")
KNOWN = np.ones((40, 40), dtype=bool)


def blob(cx=77.0, cy=28.575, sigma_m=8000.0, peak=100.0):
    r2 = ((LAT - cy) * 111320.0) ** 2 + ((LON - cx) * 111320.0 * math.cos(math.radians(28.6))) ** 2
    return peak * np.exp(-r2 / (2 * sigma_m**2))


def winds(u: float, v: float = 0.0, T: int = 7):
    return np.full((T, 40, 40), float(u)), np.full((T, 40, 40), float(v))


def centroid_km(frame: np.ndarray) -> tuple[float, float]:
    w = np.nan_to_num(frame)
    x = (w * LON).sum() / w.sum() * 111.32 * math.cos(math.radians(28.6))
    y = (w * LAT).sum() / w.sum() * 111.32
    return x, y


def test_a_blob_is_carried_downwind_by_about_u_times_t():
    u, v = winds(3.0)
    res = run_transport(G, blob(), KNOWN, u, v, [MemberParams(diffusivity_m2s=0.0)])
    C = res.concentration[0]
    dx = centroid_km(C[-1])[0] - centroid_km(C[0])[0]
    assert dx == pytest.approx(3.0 * 6 * 3.6, rel=0.05)  # 64.8 km in 6 h
    assert abs(centroid_km(C[-1])[1] - centroid_km(C[0])[1]) < 1.0  # no drift across the wind


def test_the_scheme_is_non_negative_and_does_not_create_new_maxima():
    u, v = winds(6.0, 2.0)
    res = run_transport(G, blob(), KNOWN, u, v, [MemberParams(diffusivity_m2s=120.0)])
    C = res.concentration[0]
    assert np.nanmin(C) >= 0.0
    assert np.nanmax(C) <= 100.0 * 1.02  # limited scheme: at most a tiny overshoot


def test_stability_at_extreme_wind_and_diffusivity():
    u, v = winds(30.0, -20.0)
    res = run_transport(G, blob(peak=500.0), KNOWN, u, v, [MemberParams(diffusivity_m2s=500.0)])
    assert np.isfinite(res.concentration[np.isfinite(res.concentration)]).all()
    assert res.max_courant <= 0.5  # the step adapts to the wind, so the Courant number stays bounded
    assert np.nanmax(res.concentration) <= 500.0 * 1.02 and np.nanmin(res.concentration) >= 0.0


def test_diffusion_alone_conserves_total_and_flattens_the_peak():
    u, v = winds(0.0)
    res = run_transport(G, blob(), KNOWN, u, v, [MemberParams(diffusivity_m2s=200.0)])
    C = res.concentration[0]
    assert np.nansum(C[-1]) == pytest.approx(np.nansum(C[0]), rel=1e-6)
    assert np.nanmax(C[-1]) < np.nanmax(C[0])


def test_inflow_brings_unknown_air_not_an_assumed_background():
    c0 = np.full((40, 40), 80.0)
    u, v = winds(5.0, T=7)  # westerly wind, 5 m/s for 6 h = 108 km: the whole domain is replaced
    res = run_transport(G, c0, KNOWN, u, v, [MemberParams(diffusivity_m2s=0.0)])
    C = res.concentration[0]
    assert np.isfinite(C[0]).all()
    assert np.isnan(C[-1][:, :4]).all()  # western edge: air that entered from outside has no value
    assert np.isfinite(C[3][:, -4:]).all()  # the eastern side is still the observed air after 3 h
    assert np.nanmax(C[-1]) <= 80.0 + 1e-6  # nothing is invented: no value above what was observed


def test_unknown_cells_stay_unknown_and_never_get_a_value():
    known = KNOWN.copy()
    known[:, :20] = False  # western half has no initial estimate
    u, v = winds(0.0)
    res = run_transport(G, np.full((40, 40), 50.0), known, u, v, [MemberParams(diffusivity_m2s=0.0)])
    assert np.isnan(res.concentration[0][-1][:, :10]).all()
    assert np.isfinite(res.concentration[0][-1][:, 30:]).all()


def test_results_are_reproducible_bit_for_bit():
    u, v = winds(2.5, 1.0)
    a = run_transport(G, blob(), KNOWN, u, v, [MemberParams()])
    b = run_transport(G, blob(), KNOWN, u, v, [MemberParams()])
    assert np.array_equal(a.concentration, b.concentration, equal_nan=True) and a.steps == b.steps


def test_parameters_do_what_they_say():
    u, v = winds(2.0, T=4)  # 3 h: the faster blob stays inside the domain
    base, fast, lossy = run_transport(G, blob(), KNOWN, u, v, [MemberParams(diffusivity_m2s=0.0), MemberParams(diffusivity_m2s=0.0, wind_scale=2.0),
                                                                MemberParams(diffusivity_m2s=0.0, loss_per_hour=0.1)]).concentration
    d_base = centroid_km(base[-1])[0] - centroid_km(base[0])[0]
    d_fast = centroid_km(fast[-1])[0] - centroid_km(fast[0])[0]
    assert d_fast == pytest.approx(2 * d_base, rel=0.08)
    assert np.nansum(lossy[-1]) / np.nansum(base[-1]) == pytest.approx(math.exp(-0.1 * 3), rel=0.02)
    rot = run_transport(G, blob(), KNOWN, u, v, [MemberParams(diffusivity_m2s=0.0, wind_rotation_deg=90.0)]).concentration[0]
    assert centroid_km(rot[-1])[1] < centroid_km(rot[0])[1] - 10.0  # a westerly turned clockwise by 90 degrees blows toward the south


def test_column_dilution_only_when_the_boundary_layer_deepens():
    u, v = winds(0.0)
    c0 = np.full((40, 40), 100.0)
    blh_up = np.stack([np.full((40, 40), 200.0 * (2 if t >= 1 else 1)) for t in range(7)])
    blh_down = blh_up[::-1].copy()
    dil = MemberParams(diffusivity_m2s=0.0, mixing_mode="column_dilution", aloft_ratio=0.0)
    up = run_transport(G, c0, KNOWN, u, v, [dil], blh_frames=blh_up).concentration[0]
    down = run_transport(G, c0, KNOWN, u, v, [dil], blh_frames=blh_down).concentration[0]
    assert np.nanmean(up[-1]) == pytest.approx(50.0, rel=1e-6)  # depth doubled, clean air aloft: halved
    assert np.nanmax(down[-1]) <= 100.0 + 1e-9  # a shallowing layer never concentrates the air
    with pytest.raises(ValueError):
        run_transport(G, c0, KNOWN, u, v, [dil], blh_frames=None)


def test_missing_wind_is_refused_not_filled():
    u, v = winds(3.0)
    u[2, 5, 5] = np.nan
    with pytest.raises(ValueError):
        run_transport(G, blob(), KNOWN, u, v, [MemberParams()])
    with pytest.raises(ValueError):
        run_transport(G, blob(), KNOWN, u[:1], v[:1], [MemberParams()])


def test_regridding_reproduces_a_linear_field_exactly_and_refuses_extrapolation():
    src_lats, src_lons = np.linspace(28.1, 29.05, 8), np.linspace(76.7, 77.8, 9)
    f = 2.0 * src_lats[:, None] + 3.0 * src_lons[None, :]
    out = regrid_bilinear(f, src_lats, src_lons, G.lats, G.lons)
    assert np.allclose(out, 2.0 * G.lats[:, None] + 3.0 * G.lons[None, :])
    with pytest.raises(ValueError):
        regrid_bilinear(f, src_lats, src_lons, np.array([27.0, 28.5]), G.lons)


def test_rotation_is_clockwise():
    u, v = rotate_wind(np.array([1.0]), np.array([0.0]), 90.0)
    assert u[0] == pytest.approx(0.0, abs=1e-12) and v[0] == pytest.approx(-1.0)
