"""A coupled, reduced-form multi-species model for Delhi-NCR: transport of five species with the physical couplings that connect them to
the weather and to each other.

This is NOT a chemistry-transport model (WRF-Chem, CAMS) and is not presented as one. It is a transparent set of first-order processes on
top of the project's advection-diffusion engine (`app.twin.transport`), each one switchable and each parameter shown to the user.

Species (what is transported)
  pm25        PM2.5 mass (ug/m3)
  pm_coarse   PM10 - PM2.5 (ug/m3): transported separately because it is removed at a different rate; PM10 is recovered as pm25 + pm_coarse,
              so PM10 >= PM2.5 holds by construction (the two separately trained/observed series can violate it)
  no2, o3, so2 gases (ug/m3)
Derived (never transported on their own): pm10 = pm25 + pm_coarse;  ox = O3 + NO2 in ppb, the quantity that NO titration leaves nearly
unchanged, so it is a better tracer of regional air than O3 alone.

Couplings (each can be switched off; every number is a documented order-of-magnitude literature value, not fitted to this city)
  meteorology -> species
    wind advection and eddy diffusion         all species, the 10 m weather-model wind
    ventilation                               OFF by default. Primary species relax toward C_ref * VC_ref / VC, VC = boundary-layer depth * wind
                                              speed: the steady-emissions rule (twice the ventilation, half the concentration). Two-sided. ASSUMES
                                              emissions stay as at the start. In the historical hindcast it made results WORSE, so it is opt-in.
    mixed-layer dilution                      OFF by default. One-sided: concentrations fall when the boundary layer deepens and nothing
                                              replaces them, because there are no emissions. Only meaningful if you accept that bias.
    dry deposition / settling                 first order, rate = v_d / H  (H: boundary-layer depth)  per species
    wet scavenging by rain                    first order, rate = a * P^b  (P: hourly rain, mm/h)  PM and (weakly) SO2
  species -> species
    SO2 -> sulfate aerosol                    first-order oxidation scaled by shortwave radiation; each unit of SO2 lost adds 1.5 units
                                              (96/64) of PM2.5 where PM2.5 is known
    PM2.5 / coarse split                      see above
Not modelled: emissions (so there is no source term: concentrations can only be carried, diluted or removed), NO titration of O3 (NO is
not observed in the stored data), NO2 -> nitrate (needs NH3 and temperature partitioning), organic aerosol, vertical structure, terrain.

Numerics are those of `transport.py`: limited second-order upwind advection, explicit Euler, open boundaries, validity tracking
(a cell is "unknown" until air with a known value reaches it, and unknown air that enters stays unknown).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from app.twin.transport import H_MAX, H_MIN, KNOWN_THRESHOLD, Grid, _advective_tendency, _diffusion

SPECIES = ("pm25", "pm_coarse", "no2", "o3", "so2")
LABELS = {"pm25": "PM2.5", "pm_coarse": "Coarse PM (PM10 - PM2.5)", "no2": "NO2", "o3": "O3", "so2": "SO2"}
PROCESSES = ("ventilation", "dilution", "deposition", "washout", "oxidation")
# Ventilation and dilution are opt-in. Dilution is one-sided (see above). Ventilation was on by default until the 22-window hindcast
# (docs/coupled-evaluation.md) showed it LOWERED skill against both passive transport and persistence, so it is no longer a default.
DEFAULT_PROCESSES = frozenset({"deposition", "washout", "oxidation"})
PRIMARY = ("pm25", "pm_coarse", "no2", "so2")  # species whose concentration follows ventilation; O3 is secondary and is left to chemistry

# 1 ppb in ug/m3 at 25 C and 1 atm
UG_PER_PPB = {"o3": 1.96, "no2": 1.88, "so2": 2.62}
SULFATE_PER_SO2 = 96.0 / 64.0
SW_REFERENCE = 800.0  # W/m2: the radiation at which the oxidation rate equals its stated daytime maximum


@dataclass(frozen=True)
class CouplingParams:
    """Everything a user can see and change. Defaults are order-of-magnitude literature values (Seinfeld & Pandis, Ch. 19-20)."""

    diffusivity_m2s: float = 50.0
    aloft_ratio: float = 0.0
    # dry deposition velocity (cm/s); PM coarse includes gravitational settling
    v_dep_cm_s: tuple[tuple[str, float], ...] = (("pm25", 0.10), ("pm_coarse", 0.60), ("no2", 0.15), ("o3", 0.40), ("so2", 0.50))
    # wet scavenging: rate = a * P^b (1/s, P in mm/h) times a per-species efficiency
    washout_a: float = 1.0e-4
    washout_b: float = 0.79
    washout_efficiency: tuple[tuple[str, float], ...] = (("pm25", 1.0), ("pm_coarse", 2.0), ("no2", 0.0), ("o3", 0.0), ("so2", 0.3))
    # SO2 -> sulfate: first order, per hour at SW_REFERENCE
    so2_oxidation_per_hour: float = 0.02
    # ventilation: relaxation time (h), the lowest wind that counts (m/s) and the bounds of the concentration ratio
    ventilation_tau_h: float = 3.0
    min_wind_m_s: float = 0.5
    ventilation_ratio_bounds: tuple[float, float] = (0.25, 4.0)

    def vdep(self, s: str) -> float:
        return dict(self.v_dep_cm_s).get(s, 0.0)

    def wash(self, s: str) -> float:
        return dict(self.washout_efficiency).get(s, 0.0)


@dataclass
class CoupledResult:
    concentration: dict[str, np.ndarray]  # species -> (T, rows, cols), NaN where unknown
    budget: dict[str, dict[str, float]]  # species -> process -> cumulative removed as a share of the initial known burden (oxidation gain for pm25 is negative)
    burden0: dict[str, float]
    steps: int
    dt_min_s: float
    dt_max_s: float
    max_courant: float
    domain_mean: dict[str, np.ndarray] = field(default_factory=dict)  # species -> (T,) mean over known cells


def _interp(frames: np.ndarray, k: int, alpha: float) -> np.ndarray:
    return (1 - alpha) * frames[k] + alpha * frames[min(k + 1, frames.shape[0] - 1)]


def run_coupled(
    grid: Grid,
    c0: dict[str, np.ndarray],
    known0: dict[str, np.ndarray],
    u_frames: np.ndarray,
    v_frames: np.ndarray,
    blh_frames: np.ndarray,
    precip_frames: np.ndarray,
    sw_frames: np.ndarray,
    params: CouplingParams = CouplingParams(),
    enabled: frozenset[str] | set[str] = DEFAULT_PROCESSES,
    cfl: float = 0.4,
    max_dt_s: float = 600.0,
) -> CoupledResult:
    """Integrate hour by hour. Frames are (T, rows, cols) at t = 0..T-1 hours. `precip_frames[k]` is the rain of the hour ENDING at t_k, so the
    interval [k, k+1] uses frame k+1. Species missing from c0/known0 are treated as entirely unknown (they stay unknown)."""
    T = u_frames.shape[0]
    shape = (grid.rows, grid.cols)
    for name, fr in (("u", u_frames), ("v", v_frames), ("blh", blh_frames), ("precip", precip_frames), ("sw", sw_frames)):
        if fr.shape != (T, *shape):
            raise ValueError(f"{name} frames must be (T, rows, cols) like the wind")
    if T < 2:
        raise ValueError("at least two frames are needed")
    if not (np.isfinite(u_frames).all() and np.isfinite(v_frames).all()):
        raise ValueError("wind frames contain missing values; the engine does not fill them")
    for fr, nm in ((blh_frames, "boundary-layer height"), (precip_frames, "precipitation"), (sw_frames, "radiation")):
        if not np.isfinite(fr).all():
            raise ValueError(f"{nm} frames contain missing values; the engine does not fill them")
    unknown = enabled - set(PROCESSES)
    if unknown:
        raise ValueError(f"unknown process: {', '.join(sorted(unknown))}")

    S = len(SPECIES)
    M = np.zeros((S, *shape))
    P = np.zeros((S, *shape))
    for i, s in enumerate(SPECIES):
        if s in known0 and known0[s].any():
            kn = known0[s].astype(bool)
            if np.nanmin(c0[s][kn]) < 0:
                raise ValueError(f"initial {s} must be non-negative")
            M[i] = kn
            P[i] = np.where(kn, c0[s], 0.0)
    K = np.full(S, float(params.diffusivity_m2s))
    dx, dy = grid.dx_m, grid.dy_m
    vd = np.array([params.vdep(s) / 100.0 for s in SPECIES])[:, None, None]  # m/s
    eff = np.array([params.wash(s) for s in SPECIES])[:, None, None]
    ip, ipc, iso2 = SPECIES.index("pm25"), SPECIES.index("pm_coarse"), SPECIES.index("so2")
    k_ox_max = params.so2_oxidation_per_hour / 3600.0
    primary = np.array([s in PRIMARY for s in SPECIES])[:, None, None]
    ref_c = np.where(M >= KNOWN_THRESHOLD, P / np.maximum(M, 1e-12), 0.0)  # the initial field each cell relaxes toward (scaled by ventilation)
    spd0 = np.maximum(np.hypot(u_frames[0], v_frames[0]), params.min_wind_m_s)
    vc_ref = np.clip(blh_frames[0], H_MIN, H_MAX) * spd0
    lo_r, hi_r = params.ventilation_ratio_bounds
    tau_s = max(params.ventilation_tau_h, 1e-3) * 3600.0

    burden0 = {s: float(P[i].sum()) for i, s in enumerate(SPECIES)}
    removed = {s: {p: 0.0 for p in PROCESSES} for s in SPECIES}

    def snapshot(P_, M_):
        return np.where(M_ >= KNOWN_THRESHOLD, P_ / np.maximum(M_, 1e-12), np.nan)

    out = np.full((S, T, *shape), np.nan)
    out[:, 0] = snapshot(P, M)
    steps, dts, max_c = 0, [], 0.0
    h_prev = np.clip(blh_frames[0], H_MIN, H_MAX)
    for k in range(T - 1):
        umax = max(np.abs(u_frames[k]).max(), np.abs(u_frames[k + 1]).max())
        vmax = max(np.abs(v_frames[k]).max(), np.abs(v_frames[k + 1]).max())
        denom = umax / dx + vmax / dy
        dt_adv = cfl / denom if denom > 0 else max_dt_s
        dt_dif = 0.2 * min(dx, dy) ** 2 / max(float(K.max()), 1e-9) / 2.0
        n = max(1, math.ceil(3600.0 / min(dt_adv, dt_dif, max_dt_s)))
        dt = 3600.0 / n
        rain = np.maximum(precip_frames[min(k + 1, T - 1)], 0.0)  # mm/h over the interval
        for s_i in range(n):
            a = (s_i + 0.5) / n
            u = np.broadcast_to(_interp(u_frames, k, a), P.shape)
            v = np.broadcast_to(_interp(v_frames, k, a), P.shape)
            max_c = max(max_c, float(np.abs(u).max() * dt / dx + np.abs(v).max() * dt / dy))
            for Q in (P, M):
                Q += dt * (_advective_tendency(Q, u, v, dx, dy, dt) + _diffusion(Q, K, dx, dy))
            np.clip(M, 0.0, 1.0, out=M)
            np.maximum(P, 0.0, out=P)
            H = np.clip(_interp(blh_frames, k, a), H_MIN, H_MAX)[None]
            lam_dep = vd / H if "deposition" in enabled else np.zeros_like(P)
            lam_wash = eff * params.washout_a * np.power(rain, params.washout_b)[None] if "washout" in enabled else np.zeros_like(P)
            lam = lam_dep + lam_wash
            if "deposition" in enabled or "washout" in enabled:
                before = P.copy()
                P *= np.exp(-lam * dt)
                lost = before - P
                share = np.divide(lam_dep, lam, out=np.zeros_like(lam), where=lam > 0)
                for i, s in enumerate(SPECIES):
                    removed[s]["deposition"] += float((lost[i] * share[i]).sum())
                    removed[s]["washout"] += float((lost[i] * (1 - share[i])).sum())
            if "ventilation" in enabled:
                spd = np.maximum(np.hypot(_interp(u_frames, k, a), _interp(v_frames, k, a)), params.min_wind_m_s)
                ratio = np.clip(vc_ref / (H[0] * spd), lo_r, hi_r)  # > 1 when ventilation is weaker than at the start
                c_now = np.where(M >= KNOWN_THRESHOLD, P / np.maximum(M, 1e-12), 0.0)
                target = ref_c * ratio[None]
                dP = np.where(primary & (M >= KNOWN_THRESHOLD), M * (target - c_now) * (1.0 - math.exp(-dt / tau_s)), 0.0)
                P += dP
                np.maximum(P, 0.0, out=P)
                for i, s_ in enumerate(SPECIES):
                    removed[s_]["ventilation"] -= float(dP[i].sum())  # a gain is negative removal
            if "oxidation" in enabled:
                sw = np.clip(_interp(sw_frames, k, a) / SW_REFERENCE, 0.0, 1.5)
                lost_so2 = P[iso2] * (1.0 - np.exp(-k_ox_max * sw * dt))
                P[iso2] -= lost_so2
                gain = np.where(M[ip] >= KNOWN_THRESHOLD, SULFATE_PER_SO2 * lost_so2, 0.0)
                P[ip] += gain
                removed["so2"]["oxidation"] += float(lost_so2.sum())
                removed["pm25"]["oxidation"] -= float(gain.sum())  # a gain, so negative removal
            steps += 1
            dts.append(dt)
        if "dilution" in enabled:
            h_new = np.clip(blh_frames[k + 1], H_MIN, H_MAX)
            grow = np.maximum(h_new, h_prev)
            factor = (h_prev + params.aloft_ratio * (grow - h_prev)) / grow
            before = P.copy()
            P *= factor[None]
            diluted = before - P
            for i, s in enumerate(SPECIES):
                removed[s]["dilution"] += float(diluted[i].sum())
            h_prev = h_new
        else:
            h_prev = np.clip(blh_frames[k + 1], H_MIN, H_MAX)
        out[:, k + 1] = snapshot(P, M)

    budget = {s: {p: (removed[s][p] / burden0[s] if burden0[s] > 0 else 0.0) for p in PROCESSES} for s in SPECIES}
    mean = {s: np.array([float(np.nanmean(out[i, k])) if np.isfinite(out[i, k]).any() else np.nan for k in range(T)]) for i, s in enumerate(SPECIES)}
    return CoupledResult(
        concentration={s: out[i] for i, s in enumerate(SPECIES)}, budget=budget, burden0=burden0, steps=steps,
        dt_min_s=min(dts) if dts else 0.0, dt_max_s=max(dts) if dts else 0.0, max_courant=max_c, domain_mean=mean,
    )


def derived_fields(conc: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """PM10 (= PM2.5 + coarse) and Ox in ppb (= O3 + NO2), each NaN wherever any component is unknown."""
    out: dict[str, np.ndarray] = {}
    if "pm25" in conc and "pm_coarse" in conc:
        out["pm10"] = conc["pm25"] + conc["pm_coarse"]
    if "o3" in conc and "no2" in conc:
        out["ox_ppb"] = conc["o3"] / UG_PER_PPB["o3"] + conc["no2"] / UG_PER_PPB["no2"]
    return out
