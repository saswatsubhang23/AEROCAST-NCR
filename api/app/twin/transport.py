"""Horizontal transport of a passive scalar over Delhi-NCR: a small, deterministic advection-diffusion engine.

What it models (and nothing else)
  dC/dt + u . grad(C) = div(K grad C) - lambda C            (2-D, vertically averaged over the mixed layer)
  * advection by the weather model's 10 m wind (optionally scaled or rotated in a scenario),
  * horizontal eddy diffusion with a constant coefficient K (a parameter, not a measurement),
  * an optional first-order loss lambda (a hypothetical removal rate; zero in the baseline),
  * an optional column-dilution rule when the boundary layer deepens (clean air aloft entrained; zero re-concentration when it shallows).
What it does NOT model: emissions, chemistry, deposition, secondary aerosol formation, vertical structure, terrain, street canyons.
Concentration fields from this engine therefore say where the *observed* air would be carried by the modelled wind; they do not locate sources.

Numerics
  * Advective (non-conservative) form with a MUSCL (minmod-limited, second order) upwind flux reconstruction: values are carried with the
    wind and no artificial source appears where the 10 m wind is not divergence free. Total mass is conserved only for a non-divergent wind.
  * Explicit forward-Euler time stepping with the step limited by an unsplit CFL condition (cx + cy <= CFL) and by the diffusion limit.
  * Knowledge is tracked, not invented: the field is carried as P = C*M together with a validity field M (1 where an initial estimate
    existed, 0 elsewhere). C = P/M where M >= 0.5, otherwise the cell is "unknown". Air entering through an inflow boundary has M = 0,
    so the known region honestly shrinks as unknown air arrives.
  * Boundaries: open. Outflow leaves; inflow carries no information (zero P and M).
  * Pure numpy, no randomness: the same inputs always give the same arrays.
"""

from dataclasses import dataclass, field
import math

import numpy as np

M_PER_DEG = 111_320.0
KNOWN_THRESHOLD = 0.5
H_MIN, H_MAX = 50.0, 4000.0  # clamp for the boundary-layer depth used by column dilution


@dataclass(frozen=True)
class Grid:
    south: float
    north: float
    west: float
    east: float
    rows: int
    cols: int

    @property
    def lats(self) -> np.ndarray:
        return np.linspace(self.south, self.north, self.rows)

    @property
    def lons(self) -> np.ndarray:
        return np.linspace(self.west, self.east, self.cols)

    @property
    def dy_m(self) -> float:
        return (self.north - self.south) / (self.rows - 1) * M_PER_DEG

    @property
    def dx_m(self) -> float:
        mid = math.radians((self.north + self.south) / 2)
        return (self.east - self.west) / (self.cols - 1) * M_PER_DEG * math.cos(mid)


@dataclass(frozen=True)
class MemberParams:
    """The parameters that define one model realisation. Everything a scenario can change is here, in the open."""

    diffusivity_m2s: float = 50.0
    wind_scale: float = 1.0
    wind_rotation_deg: float = 0.0  # clockwise; +20 turns a wind from the west into one from the north-west
    loss_per_hour: float = 0.0
    mixing_mode: str = "none"  # "none" or "column_dilution"
    aloft_ratio: float = 0.0  # concentration aloft as a fraction of the surface value, used only by column_dilution


@dataclass
class TransportResult:
    times_s: list[float]
    concentration: np.ndarray  # (members, T, rows, cols) with NaN where unknown
    steps: int
    dt_min_s: float
    dt_max_s: float
    max_courant: float
    mass_known: np.ndarray = field(default_factory=lambda: np.zeros(0))  # (members, T) sum of C over known cells


def regrid_bilinear(src: np.ndarray, src_lats: np.ndarray, src_lons: np.ndarray, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Bilinear resampling of src[..., rows, cols] onto a regular grid inside the source lattice (no extrapolation: points outside raise)."""
    if lats.min() < src_lats[0] - 1e-9 or lats.max() > src_lats[-1] + 1e-9 or lons.min() < src_lons[0] - 1e-9 or lons.max() > src_lons[-1] + 1e-9:
        raise ValueError("target grid is not inside the source lattice")
    r = np.clip(np.searchsorted(src_lats, lats, side="right") - 1, 0, len(src_lats) - 2)
    c = np.clip(np.searchsorted(src_lons, lons, side="right") - 1, 0, len(src_lons) - 2)
    ty = ((lats - src_lats[r]) / (src_lats[r + 1] - src_lats[r]))[:, None]
    tx = ((lons - src_lons[c]) / (src_lons[c + 1] - src_lons[c]))[None, :]
    a = src[..., r[:, None], c[None, :]]
    b = src[..., r[:, None], c[None, :] + 1]
    d = src[..., r[:, None] + 1, c[None, :]]
    e = src[..., r[:, None] + 1, c[None, :] + 1]
    return a * (1 - tx) * (1 - ty) + b * tx * (1 - ty) + d * (1 - tx) * ty + e * tx * ty


def _minmod(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.where(a * b > 0.0, np.where(np.abs(a) < np.abs(b), a, b), 0.0)


def _advective_tendency(Q: np.ndarray, u: np.ndarray, v: np.ndarray, dx: float, dy: float, dt: float) -> np.ndarray:
    """-u.grad(Q) in advective form: -div(uQ) + Q div(u), with limited second-order upwind face values. Arrays are (m, rows, cols)."""
    out = np.zeros_like(Q)
    for axis, w, h in ((2, u, dx), (1, v, dy)):
        Qe = np.pad(Q, [(0, 0), (1, 1), (0, 0)] if axis == 1 else [(0, 0), (0, 0), (1, 1)])  # zero ghost cells: open boundary, inflow = unknown
        if axis == 1:
            Qe = np.moveaxis(Qe, 1, 2)
            wm = np.moveaxis(w, 1, 2)
        else:
            wm = w
        n = Qe.shape[-1] - 2
        slope = np.zeros_like(Qe)
        slope[..., 1:-1] = _minmod(Qe[..., 1:-1] - Qe[..., :-2], Qe[..., 2:] - Qe[..., 1:-1])
        # velocity on the n+1 faces: mean of neighbours inside, the cell value at the two boundary faces
        wf = np.empty(wm.shape[:-1] + (n + 1,))
        wf[..., 1:-1] = 0.5 * (wm[..., :-1] + wm[..., 1:])
        wf[..., 0] = wm[..., 0]
        wf[..., -1] = wm[..., -1]
        courant = np.abs(wf) * dt / h
        left, right = np.arange(0, n + 1), np.arange(1, n + 2)  # padded indices of the cells on each side of face f
        q_left = Qe[..., left] + 0.5 * slope[..., left] * (1.0 - courant)
        q_right = Qe[..., right] - 0.5 * slope[..., right] * (1.0 - courant)
        qf = np.where(wf >= 0.0, q_left, q_right)
        flux = wf * qf
        tend = -(flux[..., 1:] - flux[..., :-1]) / h + Qe[..., 1:-1] * (wf[..., 1:] - wf[..., :-1]) / h
        out += np.moveaxis(tend, 2, 1) if axis == 1 else tend
    return out


def _diffusion(Q: np.ndarray, K: np.ndarray, dx: float, dy: float) -> np.ndarray:
    Qe = np.pad(Q, [(0, 0), (1, 1), (1, 1)], mode="edge")  # zero-gradient: diffusion does not drain the domain through the walls
    lap = (Qe[:, 1:-1, 2:] - 2 * Q + Qe[:, 1:-1, :-2]) / dx**2 + (Qe[:, 2:, 1:-1] - 2 * Q + Qe[:, :-2, 1:-1]) / dy**2
    return K[:, None, None] * lap


def rotate_wind(u: np.ndarray, v: np.ndarray, degrees: float) -> tuple[np.ndarray, np.ndarray]:
    """Turn the wind vector clockwise by `degrees` (a scenario operation)."""
    t = math.radians(degrees)
    return u * math.cos(t) + v * math.sin(t), -u * math.sin(t) + v * math.cos(t)


def run_transport(
    grid: Grid,
    c0: np.ndarray,
    known0: np.ndarray,
    u_frames: np.ndarray,
    v_frames: np.ndarray,
    members: list[MemberParams],
    blh_frames: np.ndarray | None = None,
    cfl: float = 0.4,
    max_dt_s: float = 600.0,
) -> TransportResult:
    """Integrate hour by hour. u_frames, v_frames (and blh_frames) are (T, rows, cols) at t = 0, 1, ..., T-1 hours; the wind is interpolated
    linearly in time between frames. c0 is the initial concentration (values where known0 is True are used, others ignored).
    Returns concentration frames (members, T, rows, cols), NaN where the field is unknown."""
    T = u_frames.shape[0]
    if T < 2 or v_frames.shape != u_frames.shape or u_frames.shape[1:] != (grid.rows, grid.cols):
        raise ValueError("wind frames must be (T >= 2, rows, cols)")
    if not (np.isfinite(u_frames).all() and np.isfinite(v_frames).all()):
        raise ValueError("wind frames contain missing values; the transport engine does not fill them")
    if np.nanmin(c0[known0]) < 0 if known0.any() else False:
        raise ValueError("initial concentrations must be non-negative")
    m = len(members)
    K = np.array([mp.diffusivity_m2s for mp in members], dtype=float)
    lam = np.array([mp.loss_per_hour for mp in members], dtype=float) / 3600.0
    scale = np.array([mp.wind_scale for mp in members], dtype=float)[:, None, None]
    rot = [mp.wind_rotation_deg for mp in members]
    dilute = np.array([mp.mixing_mode == "column_dilution" for mp in members])
    aloft = np.array([mp.aloft_ratio for mp in members], dtype=float)[:, None, None]
    if dilute.any() and blh_frames is None:
        raise ValueError("column dilution needs boundary-layer height frames")

    M = np.broadcast_to(known0.astype(float), (m, grid.rows, grid.cols)).copy()
    P = np.where(M > 0, np.broadcast_to(np.where(known0, c0, 0.0), M.shape), 0.0)
    dx, dy = grid.dx_m, grid.dy_m

    def wind(k0: int, alpha: float) -> tuple[np.ndarray, np.ndarray]:
        u = (1 - alpha) * u_frames[k0] + alpha * u_frames[min(k0 + 1, T - 1)]
        v = (1 - alpha) * v_frames[k0] + alpha * v_frames[min(k0 + 1, T - 1)]
        us, vs = [], []
        for r in rot:
            ur, vr = rotate_wind(u, v, r) if r else (u, v)
            us.append(ur)
            vs.append(vr)
        return np.stack(us) * scale, np.stack(vs) * scale

    out = np.full((m, T, grid.rows, grid.cols), np.nan)
    out[:, 0] = np.where(M >= KNOWN_THRESHOLD, P / np.maximum(M, 1e-12), np.nan)
    steps = 0
    dts: list[float] = []
    max_c = 0.0
    h_prev = None if blh_frames is None else np.clip(blh_frames[0], H_MIN, H_MAX)
    for k in range(T - 1):
        # step size for this hour from the fastest wind of either bounding frame, over all members
        u0, v0 = wind(k, 0.0)
        u1, v1 = wind(k, 1.0)
        umax = max(np.abs(u0).max(), np.abs(u1).max())
        vmax = max(np.abs(v0).max(), np.abs(v1).max())
        denom = umax / dx + vmax / dy
        dt_adv = cfl / denom if denom > 0 else max_dt_s
        dt_dif = 0.2 * min(dx, dy) ** 2 / max(float(K.max()), 1e-9) / 2.0
        n = max(1, math.ceil(3600.0 / min(dt_adv, dt_dif, max_dt_s)))
        dt = 3600.0 / n
        for s in range(n):
            u, v = wind(k, (s + 0.5) / n)
            max_c = max(max_c, float(np.abs(u).max() * dt / dx + np.abs(v).max() * dt / dy))
            for Q in (P, M):
                Q += dt * (_advective_tendency(Q, u, v, dx, dy, dt) + _diffusion(Q, K, dx, dy))
            np.clip(M, 0.0, 1.0, out=M)
            np.maximum(P, 0.0, out=P)
            P *= np.exp(-lam * dt)[:, None, None]
            steps += 1
            dts.append(dt)
        if blh_frames is not None and dilute.any():
            h_new = np.clip(blh_frames[k + 1], H_MIN, H_MAX)
            grow = np.maximum(h_new, h_prev)  # a deepening layer dilutes; a shallowing one does not re-concentrate
            factor = (h_prev + aloft * (grow - h_prev)) / grow
            P = np.where(dilute[:, None, None], P * factor, P)
            h_prev = h_new
        out[:, k + 1] = np.where(M >= KNOWN_THRESHOLD, P / np.maximum(M, 1e-12), np.nan)
    mass = np.nansum(np.where(np.isnan(out), 0.0, out), axis=(2, 3))
    return TransportResult(times_s=[3600.0 * k for k in range(T)], concentration=out, steps=steps, dt_min_s=min(dts) if dts else 0.0,
                           dt_max_s=max(dts) if dts else 0.0, max_courant=max_c, mass_known=mass)
