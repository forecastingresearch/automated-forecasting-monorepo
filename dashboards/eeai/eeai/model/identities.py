"""The design note's accounting identities, over many simulated worlds at once.

Every input is an array whose first axis is the world. `base` holds the 2025
baselines (by symbol: N0, H0, E0, lambda0 (worlds, industries); sigma0
(worlds, industries, occupations); u0, omega0, sA0.. (worlds, occupations);
n0, Pop0, p10_0.. (worlds,)). `fut` holds the forecast years, a year axis
after the world axis (Q (worlds, years, industries), sigma (worlds, years,
industries, occupations), ...). `gaps` is each forecast year's distance from
the one before (2026 from 2025 is 1; 2035 from 2030 is 5).

The returned outcomes carry 2025 as year 0, so every series starts there; a
growth rate has no value for 2025 (NaN). Growth is an annual rate: year on
year where the gap is one year, the average annual rate over the gap where it
is longer. Units: N0 in US$ billions and H0 in millions of hours, so pay per
hour is N/H x 1000 dollars.

The outcomes also carry the inputs they were computed from ("in." + symbol,
as drawn, 2025 first) and a few intermediate totals, so the page can show
how each outcome is put together.
"""
import numpy as np


def _with_base(base_value, fut_value):
    """Prepend the 2025 value as year 0: (worlds, ...) + (worlds, years, ...) -> (worlds, 1 + years, ...)."""
    return np.concatenate([np.asarray(base_value)[:, None], fut_value], axis=1)


def _rate(ratio, gaps):
    """A ratio over each gap -> the annual rate, with 2025 NaN. ratio (worlds, years, ...)."""
    g = np.asarray(gaps, dtype=float).reshape((1, -1) + (1,) * (ratio.ndim - 2))
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.power(ratio, 1 / g) - 1
    return np.concatenate([np.full_like(r[:, :1], np.nan), r], axis=1)


def compute(base, fut, gaps):
    """-> (outcomes, counts). outcomes: {name: (worlds, 1 + years[, k])}; counts: rescaling tallies for the diagnostics."""
    W = base["N0"].shape[0]
    ones_i = np.ones_like(base["N0"])
    Q = _with_base(ones_i, fut["Q"])
    P = _with_base(ones_i, fut["P"])
    PI = _with_base(ones_i, fut["pi"])
    K = _with_base(ones_i, fut["K"])
    lam = _with_base(base["lambda0"], fut["lambda"])

    # Output: nominal value added, weights, the Fisher chain, contributions, the deflator.
    N_i = base["N0"][:, None, :] * Q * P                       # (W, T+1, I)
    N = N_i.sum(-1)
    w = N_i / N[..., None]
    x = Q[:, 1:] / Q[:, :-1]
    laspeyres = (w[:, :-1] * x).sum(-1)
    paasche = 1 / (w[:, 1:] / x).sum(-1)
    step = np.sqrt(laspeyres * paasche)                          # G_t / G_t'
    G = np.concatenate([np.ones((W, 1)), np.cumprod(step, axis=1)], axis=1)
    wbar = (w[:, :-1] + w[:, 1:]) / 2
    sector_growth = _rate(x, gaps)
    sector_contribution = np.concatenate([np.full((W, 1, w.shape[-1]), np.nan), sector_growth[:, 1:] * wbar], axis=1)
    D = N / (N[:, :1] * G)

    # Hours and labor productivity.
    H_i = base["H0"][:, None, :] * Q / PI
    H = H_i.sum(-1)
    LP = G / (H / H[:, :1])

    # Employment by industry and occupation; the occupation shares renormalized in every world.
    E_i = np.concatenate([base["E0"][:, None, :], H_i[:, 1:] / fut["h"]], axis=1)
    sig_raw = np.concatenate([base["sigma0"][:, None], fut["sigma"]], axis=1)   # (W, T+1, I, O)
    sig_sum = sig_raw.sum(-1)
    sig = sig_raw / sig_sum[..., None]
    E_io = E_i[..., None] * sig
    E_o = E_io.sum(-2)                                           # (W, T+1, O)
    E = E_i.sum(-1)

    # Unemployment and participation.
    u = np.concatenate([base["u0"][:, None], fut["u"]], axis=1)
    n = np.concatenate([base["n0"][:, None], fut["n"]], axis=1)
    pop = np.concatenate([base["Pop0"][:, None], fut["Pop"]], axis=1)
    U_o = E_o * u / (1 - u)
    L = (E + U_o.sum(-1)) / (1 - n)

    # Capital, TFP, the labor share and pay per hour.
    lbar = (lam[:, :-1] + lam[:, 1:]) / 2
    dlnA_i = np.log(x) - (1 - lbar) * np.log(K[:, 1:] / K[:, :-1]) - lbar * np.log(H_i[:, 1:] / H_i[:, :-1])
    dlnA = (wbar * dlnA_i).sum(-1)
    tfp_growth = _rate(np.exp(dlnA), gaps)
    TFP = np.concatenate([np.ones((W, 1)), np.exp(np.cumsum(dlnA, axis=1))], axis=1)
    LAM = (w * lam).sum(-1)
    c = LAM * N / H * 1000                                       # dollars per hour, current prices

    # Wages: consumer prices relative to their own 2025 value.
    C = np.concatenate([base["C0"][:, None], fut["C"]], axis=1)
    C = C / C[:, :1]
    real_pay = c / C / c[:, :1]
    p10 = np.concatenate([base["p10_0"][:, None], fut["p10"]], axis=1)
    p50 = np.concatenate([base["p50_0"][:, None], fut["p50"]], axis=1)
    p90 = np.concatenate([base["p90_0"][:, None], fut["p90"]], axis=1)
    omega = np.concatenate([base["omega0"][:, None], fut["omega"]], axis=1)
    eci = np.concatenate([base["ECI0"][:, None], fut["ECI"]], axis=1)

    # Automation: shares above one in sum are scaled down to one.
    sA = np.concatenate([base["sA0"][:, None], fut["sA"]], axis=1)
    sM = np.concatenate([base["sM0"][:, None], fut["sM"]], axis=1)
    rA = np.concatenate([base["rA0"][:, None], fut["rA"]], axis=1)
    rM = np.concatenate([base["rM0"][:, None], fut["rM"]], axis=1)
    over = sA + sM > 1
    scale = np.where(over, 1 / (sA + sM), 1.0)
    sA, sM = sA * scale, sM * scale
    m = (1 - sA - sM) + sA * rA + sM * rM
    per_gdp = (E_o / G[..., None]) / (E_o[:, :1] / G[:, :1, None])
    d = per_gdp / (m / m[:, :1])
    absorbed = (E_o * (m[:, :1] / m - 1)).sum(-1)

    out = {
        "gdp_growth": _rate(step, gaps) * 100,
        "gdp_index": G,
        "nominal_gdp": N / 1000,                                 # US$ trillions
        "inflation_gdp": _rate(D[:, 1:] / D[:, :-1], gaps) * 100,
        "inflation_pce": _rate(C[:, 1:] / C[:, :-1], gaps) * 100,
        "lp_growth": _rate(LP[:, 1:] / LP[:, :-1], gaps) * 100,
        "tfp_growth": tfp_growth * 100,
        "tfp_index": TFP,
        "employment": E,
        "unemployment_rate": (1 - E / L) * 100,
        "lfpr": L / pop * 100,
        "epop": E / pop * 100,
        "labor_share": LAM * 100,
        "pay_per_hour": c,
        "real_pay_index": real_pay,
        "real_pay_growth": _rate(real_pay[:, 1:] / real_pay[:, :-1], gaps) * 100,
        "real_pay_lp": LP,
        "real_pay_labor_share": LAM / LAM[:, :1],
        "real_pay_price_gap": D / C,
        "real_median_earnings": p50 / C,
        "ratio_90_10": p90 / p10,
        "eci_real": eci / eci[:, :1] / C,
        "work_absorbed": absorbed,
        "sector_growth": sector_growth * 100,
        "sector_contribution": sector_contribution * 100,
        "sector_share": w * 100,
        "occupation_employment": E_o,
        "occupation_unemployment": u * 100,
        "occupation_premium": omega / p50[..., None],
        "occupation_time": m,
        "occupation_demand": d,
        # The intermediate totals the page's detail cards show between inputs and outcomes.
        "hours": H,                                              # millions of hours
        "unemployed": U_o.sum(-1),                               # millions, in an occupation group
        "labor_force": L,                                        # millions
        # The forecast inputs themselves, 2025 (the baselines) first, for the detail cards.
        # Percent where the component is a share; h for 2025 is hours over employment.
        "in.Q": Q, "in.P": P, "in.pi": PI, "in.K": K, "in.lambda": lam * 100,
        "in.h": np.concatenate([(base["H0"] / base["E0"])[:, None], fut["h"]], axis=1),
        "in.E": E_i,
        "in.u": u * 100, "in.n": n * 100, "in.Pop": pop, "in.C": C,
        "in.p10": p10, "in.p50": p50, "in.p90": p90,
    }
    counts = {"share_sum": sig_sum[:, 1:], "automation_rescaled": over[:, 1:]}
    return out, counts


def baseline_totals(base):
    """The 2025 totals the identities give from baselines (one world each) -> {name: (worlds,)}:
    nominal GDP (US$ billions), employment (millions), unemployment rate and LFPR (percent)."""
    sig = base["sigma0"] / base["sigma0"].sum(-1, keepdims=True)
    E_o = (base["E0"][..., None] * sig).sum(-2)
    E = base["E0"].sum(-1)
    U = (E_o * base["u0"] / (1 - base["u0"])).sum(-1)
    L = (E + U) / (1 - base["n0"])
    return {"nominal_gdp": base["N0"].sum(-1), "employment": E,
            "unemployment_rate": (1 - E / L) * 100, "lfpr": L / base["Pop0"] * 100}
