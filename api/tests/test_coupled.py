"""The coupled engine: every coupling is checked against what physics says it must do, and with all couplings off it must be the passive engine."""

import math

import numpy as np
import pytest

from app.twin.coupled import (
    PROCESSES, SPECIES, SULFATE_PER_SO2, CouplingParams, derived_fields, run_coupled,
)
from app.twin.transport import Grid, MemberParams, run_transport

G = Grid(south=28.1, north=28.4, west=77.0, east=77.3, rows=12, cols=12)
SHAPE = (G.rows, G.cols)


def frames(value: float, T: int = 7) -> np.ndarray:
    return np.full((T, *SHAPE), float(value))


def uniform(value: float) -> np.ndarray:
    return np.full(SHAPE, float(value))


def inputs(vals: dict[str, float], known: bool = True):
    c0 = {s: uniform(v) for s, v in vals.items()}
    k0 = {s: np.full(SHAPE, known) for s in vals}
    return c0, k0


def run(vals, *, u=0.0, v=0.0, blh=500.0, rain=0.0, sw=0.0, enabled=frozenset(PROCESSES), params=CouplingParams(), T=7):
    c0, k0 = inputs(vals)
    return run_coupled(G, c0, k0, frames(u, T), frames(v, T), frames(blh, T), frames(rain, T), frames(sw, T), params, enabled)


def centre(res, s, k=-1):
    return float(res.concentration[s][k][6, 6])


# ------------------------------------------------------------------------------------------------ consistency with the passive engine
def test_with_every_coupling_off_it_is_exactly_the_passive_transport_engine():
    rng = np.random.default_rng(3)
    c0 = 20 + 60 * rng.random(SHAPE)
    known = np.ones(SHAPE, dtype=bool)
    u, v = frames(2.5), frames(-1.0)
    passive = run_transport(G, c0, known, u, v, [MemberParams(50.0)]).concentration[0]
    coupled = run_coupled(G, {"pm25": c0}, {"pm25": known}, u, v, frames(500), frames(0), frames(0), CouplingParams(), frozenset())
    assert np.allclose(coupled.concentration["pm25"], passive, equal_nan=True, atol=1e-9)
    # a species that was never given stays unknown instead of becoming zero
    assert np.isnan(coupled.concentration["o3"]).all()


# ------------------------------------------------------------------------------------------------ meteorology -> species
def test_dry_deposition_decays_each_species_at_its_own_rate_v_over_H():
    vals = {s: 100.0 for s in SPECIES}
    res = run(vals, enabled=frozenset({"deposition"}), blh=400.0)
    hours = 6
    for s in SPECIES:
        v_d = CouplingParams().vdep(s) / 100.0
        expected = 100.0 * math.exp(-v_d / 400.0 * 3600.0 * hours)
        assert centre(res, s) == pytest.approx(expected, rel=2e-3), s
    assert centre(res, "pm_coarse") < centre(res, "pm25")  # coarse settles faster than fine particles
    assert centre(res, "o3") < centre(res, "no2")


def test_a_shallow_boundary_layer_removes_faster_than_a_deep_one():
    shallow = run({"pm25": 100.0}, enabled=frozenset({"deposition"}), blh=100.0)
    deep = run({"pm25": 100.0}, enabled=frozenset({"deposition"}), blh=1500.0)
    assert centre(shallow, "pm25") < centre(deep, "pm25")


def test_rain_scavenges_particles_strongly_so2_weakly_and_leaves_poorly_soluble_gases_alone():
    res = run({s: 100.0 for s in SPECIES}, enabled=frozenset({"washout"}), rain=5.0)
    a, b = CouplingParams().washout_a, CouplingParams().washout_b
    lam = a * 5.0**b  # 1/s for efficiency 1
    assert centre(res, "pm25") == pytest.approx(100.0 * math.exp(-lam * 3600 * 6), rel=2e-3)
    assert centre(res, "pm_coarse") < centre(res, "pm25") < 100.0
    assert centre(res, "so2") < 100.0 and centre(res, "so2") > centre(res, "pm25")
    assert centre(res, "no2") == pytest.approx(100.0, rel=1e-6) and centre(res, "o3") == pytest.approx(100.0, rel=1e-6)
    dry = run({"pm25": 100.0}, enabled=frozenset({"washout"}), rain=0.0)
    assert centre(dry, "pm25") == pytest.approx(100.0, rel=1e-6)


def test_rain_of_an_hour_acts_during_the_hour_it_ends_not_the_one_before():
    rain = np.zeros((7, *SHAPE))
    rain[3] = 10.0  # the hour ENDING at t=3 h, i.e. the interval 2 h -> 3 h
    c0, k0 = inputs({"pm25": 100.0})
    res = run_coupled(G, c0, k0, frames(0), frames(0), frames(500), rain, frames(0), CouplingParams(), frozenset({"washout"}))
    pm = [float(res.concentration["pm25"][k][6, 6]) for k in range(7)]
    assert pm[2] == pytest.approx(100.0) and pm[3] < 99.0 and pm[3] == pytest.approx(pm[6])


def test_boundary_layer_deepening_dilutes_and_shallowing_does_not_re_concentrate():
    c0, k0 = inputs({"pm25": 100.0})
    blh = np.stack([np.full(SHAPE, h) for h in (200.0, 400.0, 400.0, 100.0, 100.0, 100.0, 100.0)])
    res = run_coupled(G, c0, k0, frames(0), frames(0), blh, frames(0), frames(0), CouplingParams(), frozenset({"dilution"}))
    pm = [float(res.concentration["pm25"][k][6, 6]) for k in range(7)]
    assert pm[1] == pytest.approx(50.0, rel=1e-6)  # depth doubled, clean air aloft: halved
    assert pm[3] == pytest.approx(50.0, rel=1e-6)  # the layer then shallows: no re-concentration
    aloft = run_coupled(G, c0, k0, frames(0), frames(0), blh, frames(0), frames(0), CouplingParams(aloft_ratio=0.5), frozenset({"dilution"}))
    assert float(aloft.concentration["pm25"][1][6, 6]) == pytest.approx(100.0 * (200 + 0.5 * 200) / 400, rel=1e-6)


# ------------------------------------------------------------------------------------------------ species -> species
def test_so2_oxidation_makes_sulfate_mass_exactly_in_the_stated_ratio():
    c0, k0 = inputs({"pm25": 10.0, "so2": 50.0})
    res = run_coupled(G, c0, k0, frames(0), frames(0), frames(500), frames(0), frames(800.0), CouplingParams(), frozenset({"oxidation"}))
    so2_lost = 50.0 - centre(res, "so2")
    pm_gained = centre(res, "pm25") - 10.0
    assert so2_lost > 0
    assert pm_gained == pytest.approx(SULFATE_PER_SO2 * so2_lost, rel=1e-6)
    assert centre(res, "so2") == pytest.approx(50.0 * math.exp(-0.02 * 6), rel=2e-3)  # 2 %/h at the reference radiation, 6 h
    assert res.budget["pm25"]["oxidation"] < 0 < res.budget["so2"]["oxidation"]


def test_oxidation_stops_at_night():
    c0, k0 = inputs({"pm25": 10.0, "so2": 50.0})
    res = run_coupled(G, c0, k0, frames(0), frames(0), frames(500), frames(0), frames(0.0), CouplingParams(), frozenset({"oxidation"}))
    assert centre(res, "so2") == pytest.approx(50.0) and centre(res, "pm25") == pytest.approx(10.0)


def test_sulfate_is_not_invented_where_pm25_is_unknown():
    c0 = {"so2": uniform(50.0)}
    k0 = {"so2": np.ones(SHAPE, dtype=bool)}
    res = run_coupled(G, c0, k0, frames(0), frames(0), frames(500), frames(0), frames(800.0), CouplingParams(), frozenset({"oxidation"}))
    assert np.isnan(res.concentration["pm25"]).all()
    assert centre(res, "so2") < 50.0  # the gas is still oxidised


def test_pm10_is_never_below_pm25_by_construction_and_ox_is_the_sum_in_ppb():
    res = run({"pm25": 80.0, "pm_coarse": 30.0, "o3": 98.0, "no2": 47.0}, u=2.0, rain=1.0, sw=500.0)
    d = derived_fields(res.concentration)
    ok = np.isfinite(d["pm10"])
    assert ok.any() and (d["pm10"][ok] >= res.concentration["pm25"][ok] - 1e-9).all()
    assert d["ox_ppb"][0][6, 6] == pytest.approx(98.0 / 1.96 + 47.0 / 1.88)


# ------------------------------------------------------------------------------------------------ knowledge and failure
def test_unknown_air_stays_unknown_and_is_not_filled_by_the_couplings():
    c0 = {"pm25": uniform(60.0)}
    known = np.zeros(SHAPE, dtype=bool)
    known[:, :4] = True
    res = run_coupled(G, c0, {"pm25": known}, frames(0), frames(0), frames(500), frames(2.0), frames(500), CouplingParams(), frozenset(PROCESSES))
    assert np.isnan(res.concentration["pm25"][-1][:, 8:]).all()
    assert np.isfinite(res.concentration["pm25"][-1][:, :2]).all()


def test_budget_shares_are_consistent_with_the_change_in_the_known_burden():
    res = run({"pm25": 100.0}, blh=300.0, rain=2.0, enabled=frozenset({"deposition", "washout"}))
    removed = res.budget["pm25"]["deposition"] + res.budget["pm25"]["washout"]
    remaining = centre(res, "pm25") / 100.0
    assert removed == pytest.approx(1.0 - remaining, rel=0.02)
    assert 0 < res.budget["pm25"]["deposition"] and 0 < res.budget["pm25"]["washout"]


@pytest.mark.parametrize("bad", ["precip", "blh", "sw"])
def test_missing_meteorology_is_refused_not_filled(bad):
    c0, k0 = inputs({"pm25": 50.0})
    f = {"precip": frames(0), "blh": frames(500), "sw": frames(0)}
    f[bad] = f[bad].copy()
    f[bad][2, 3, 3] = np.nan
    with pytest.raises(ValueError, match="missing values"):
        run_coupled(G, c0, k0, frames(1), frames(0), f["blh"], f["precip"], f["sw"])


def test_unknown_process_and_negative_initial_values_are_refused():
    c0, k0 = inputs({"pm25": 50.0})
    with pytest.raises(ValueError, match="unknown process"):
        run_coupled(G, c0, k0, frames(0), frames(0), frames(500), frames(0), frames(0), enabled={"magic"})
    c0["pm25"][2, 2] = -5.0
    with pytest.raises(ValueError, match="non-negative"):
        run_coupled(G, c0, k0, frames(0), frames(0), frames(500), frames(0), frames(0))


def test_the_same_inputs_give_the_same_arrays():
    a = run({"pm25": 70.0, "so2": 20.0}, u=3.0, v=1.0, rain=1.0, sw=400.0)
    b = run({"pm25": 70.0, "so2": 20.0}, u=3.0, v=1.0, rain=1.0, sw=400.0)
    assert np.array_equal(a.concentration["pm25"], b.concentration["pm25"], equal_nan=True)


# ------------------------------------------------------------------------------------------------ ventilation (two-sided, steady emissions)
def blh_series(*depths: float) -> np.ndarray:
    return np.stack([np.full(SHAPE, d) for d in depths])


def test_ventilation_holds_the_field_when_the_meteorology_does_not_change():
    res = run({"pm25": 80.0, "no2": 40.0}, u=0.5, blh=600.0, enabled=frozenset({"ventilation"}))
    assert centre(res, "pm25") == pytest.approx(80.0, rel=1e-6) and centre(res, "no2") == pytest.approx(40.0, rel=1e-6)


def test_halving_the_ventilation_raises_primary_species_toward_twice_the_level_and_leaves_ozone_alone():
    c0, k0 = inputs({"pm25": 80.0, "no2": 40.0, "o3": 60.0, "so2": 10.0})
    blh = blh_series(600.0, 300.0, 300.0, 300.0, 300.0, 300.0, 300.0)  # depth halves at hour 1 and stays
    tau = CouplingParams().ventilation_tau_h
    res = run_coupled(G, c0, k0, frames(0.0), frames(0.0), blh, frames(0), frames(0), CouplingParams(), frozenset({"ventilation"}))
    pm = [float(res.concentration["pm25"][k][6, 6]) for k in range(7)]
    assert pm[0] == pytest.approx(80.0)
    assert all(b >= a - 1e-9 for a, b in zip(pm, pm[1:]))  # rises monotonically toward the new equilibrium
    assert pm[1] > 80.0 and pm[6] < 160.0  # approaches but does not overshoot the doubled level
    # after n hours of relaxation the gap to the target has shrunk by exp(-n / tau); the target is 160
    assert 160.0 - pm[6] == pytest.approx((160.0 - pm[1]) * math.exp(-5 / tau), rel=0.05)
    assert float(res.concentration["o3"][6][6, 6]) == pytest.approx(60.0)  # secondary species: not scaled
    assert res.budget["pm25"]["ventilation"] < 0  # a gain is a negative removal


def test_stronger_wind_lowers_primary_species_and_the_change_is_bounded():
    c0, k0 = inputs({"pm25": 100.0})
    T = 5
    u = np.stack([np.full(SHAPE, w) for w in (0.3, 0.9, 0.9, 0.9, 0.9)])  # wind triples at hour 1 (gentle enough that the known air stays inside the domain)
    res = run_coupled(G, c0, k0, u, frames(0.0, T), frames(500, T), frames(0, T), frames(0, T), CouplingParams(ventilation_tau_h=0.5), frozenset({"ventilation"}))
    low = float(res.concentration["pm25"][-1][6, 6])
    assert 100.0 / 3.0 - 1.0 <= low < 60.0  # heads for a third of the starting level
    lo_bound = CouplingParams().ventilation_ratio_bounds[0]
    # ten times the wind would ask for a tenth: the ratio is held at the lower bound
    u10 = np.stack([np.full(SHAPE, w) for w in (0.05, 0.5, 0.5, 0.5, 0.5)])
    res2 = run_coupled(G, c0, k0, u10, frames(0.0, T), frames(500, T), frames(0, T), frames(0, T), CouplingParams(ventilation_tau_h=0.5, min_wind_m_s=0.05), frozenset({"ventilation"}))
    assert float(res2.concentration["pm25"][-1][6, 6]) >= 100.0 * lo_bound - 1e-6


def test_ventilation_does_not_fill_unknown_cells():
    c0 = {"pm25": uniform(60.0)}
    known = np.zeros(SHAPE, dtype=bool)
    known[:, :3] = True
    blh = blh_series(600.0, 200.0, 200.0, 200.0, 200.0, 200.0, 200.0)
    res = run_coupled(G, c0, {"pm25": known}, frames(0), frames(0), blh, frames(0), frames(0), CouplingParams(), frozenset({"ventilation"}))
    assert np.isnan(res.concentration["pm25"][-1][:, 6:]).all()


def test_the_couplings_that_lowered_skill_in_the_hindcast_are_not_defaults():
    from app.twin.coupled import DEFAULT_PROCESSES

    assert {"ventilation", "dilution"}.isdisjoint(DEFAULT_PROCESSES)
    assert DEFAULT_PROCESSES == {"deposition", "washout", "oxidation"}
