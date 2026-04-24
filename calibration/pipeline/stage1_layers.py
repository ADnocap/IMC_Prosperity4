"""Stage 1 — bot-layer detection via KDE peak finding.

Port of visualizer/src/pages/calibration/stages/layer_detection.ts.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import kernels as K
from .data import FvAndBook


@dataclass
class Quote:
    side: str
    price: int
    volume: int
    fv: float
    offset: float
    ts: int


@dataclass
class DetectedLayer:
    id: str
    name: str
    offset_mag: float
    offset_type: str          # "fixed" | "proportional"
    k_estimate: float
    bid_peak_offset: float
    ask_peak_offset: float
    offset_band: dict          # {"bid": (lo, hi), "ask": (lo, hi)}
    n_bid: int
    n_ask: int
    bid_ols: dict | None
    ask_ols: dict | None


@dataclass
class Stage1Result:
    quotes: list
    bid_kde: K.KdeOut
    ask_kde: K.KdeOut
    layers: list
    noise_quotes: list


def _extract_quotes(data: FvAndBook) -> list:
    out = []
    for r in data.rows:
        if r.fv is None:
            continue
        for bp in r.bids:
            v = r.bid_vols.get(bp, 0)
            out.append(Quote("bid", bp, v, r.fv, bp - r.fv, r.ts))
        for ap in r.asks:
            v = r.ask_vols.get(ap, 0)
            out.append(Quote("ask", ap, v, r.fv, ap - r.fv, r.ts))
    return out


def _peak_to_band(kde: K.KdeOut, peak_idx: int, mult: float = 1.5) -> tuple:
    center = kde.grid[peak_idx]
    half = kde.bandwidth * mult
    return (center - half, center + half)


def _disjoint_bands(kde: K.KdeOut, peaks: list, mult: float = 1.5) -> list:
    """Return per-peak bands such that adjacent bands don't overlap.

    Default is ±mult·bandwidth around each peak. When two adjacent peaks would
    overlap, the shared boundary is set to the midpoint between the peak centers.
    Required for products where bots sit at adjacent integer offsets (e.g.,
    VELVETFRUIT_EXTRACT inner at -3 and outer-secondary at -2/-4 — the default
    bands overlap and a quote at -3 ends up classified into TWO layers, double-
    counting it and breaking presence stats.
    """
    if not peaks:
        return []
    centers = sorted([(kde.grid[idx], idx) for idx in peaks])  # ascending offset
    bands_by_idx: dict = {}
    half = kde.bandwidth * mult
    for i, (c, idx) in enumerate(centers):
        lo = c - half
        hi = c + half
        if i > 0:
            mid = (centers[i - 1][0] + c) / 2
            lo = max(lo, mid)
        if i < len(centers) - 1:
            mid = (c + centers[i + 1][0]) / 2
            hi = min(hi, mid)
        bands_by_idx[idx] = (lo, hi)
    return [bands_by_idx[idx] for idx in peaks]


def _quotes_in_band(quotes: list, band: tuple) -> list:
    return [q for q in quotes if band[0] <= q.offset <= band[1]]


def _pair_peaks(bid_peaks: list, ask_peaks: list) -> list:
    bids = sorted(bid_peaks, key=lambda x: -x["mag"])
    asks = sorted(ask_peaks, key=lambda x: -x["mag"])
    paired = []
    used_asks: set = set()
    for b in bids:
        best_idx = -1
        best_diff = float("inf")
        for i, a in enumerate(asks):
            if i in used_asks:
                continue
            diff = abs(a["mag"] - b["mag"])
            if diff < best_diff:
                best_diff = diff; best_idx = i
        if best_idx >= 0:
            paired.append({"bid": b, "ask": asks[best_idx]})
            used_asks.add(best_idx)
        else:
            paired.append({"bid": b, "ask": None})
    for i, a in enumerate(asks):
        if i not in used_asks:
            paired.append({"bid": None, "ask": a})
    return paired


def _classify_layer(quotes: list) -> dict:
    if len(quotes) < 20:
        return {"ols": None, "proportional": False, "k": 0.0}
    fvs = [q.fv for q in quotes]
    offs = [q.offset for q in quotes]
    try:
        ols = K.ols_regress(fvs, offs)
        proportional = abs(ols.t_beta) > 3 and abs(ols.beta) > 1e-5
        k = abs(ols.beta) if proportional else 0.0
        return {"ols": ols, "proportional": proportional, "k": k}
    except Exception:
        return {"ols": None, "proportional": False, "k": 0.0}


def _integer_mode_layers(data: FvAndBook, quotes: list) -> list:
    """Detect layers by integer-binned offset modes + per-tick co-occurrence.

    For Prosperity (integer prices, fractional FV), each bot's continuous offset
    spans roughly one integer interval. KDE peak detection on these tight
    distributions struggles — adjacent bots with offsets 1 unit apart show as
    overlapping peaks and the merge rule then loses one of them.

    This integer-mode detector:
      1. Bins quote offsets to nearest integer per side.
      2. Picks all int modes with frequency >= 5% of ticks (and >= 20 quotes).
      3. Pairs bid-side and ask-side modes by |offset| nearest-match.
      4. Each (bid_int, ask_int) pair becomes one layer with band ±0.5 around the int.

    Returns the same DetectedLayer structure as the KDE pipeline. The formula
    search in Stage 2 handles distinguishing one-bot-rounding-spread from
    two-bots-at-adjacent-ints (identical formulas → merged later).
    """
    from collections import Counter as _C
    n_ticks = len([r for r in data.rows if r.fv is not None])
    if n_ticks == 0:
        return []
    bid_int = _C(); ask_int = _C()
    for q in quotes:
        if q.side == "bid": bid_int[round(q.offset)] += 1
        else:               ask_int[round(q.offset)] += 1
    # Threshold: at least 5% of ticks AND 20 quotes (so a side appearing on
    # every tick is captured even when other bots also fire on the same tick).
    thresh = max(20, int(0.05 * n_ticks))
    bid_modes = sorted([off for off, c in bid_int.items() if c >= thresh],
                        key=lambda x: -bid_int[x])  # by frequency desc
    ask_modes = sorted([off for off, c in ask_int.items() if c >= thresh],
                        key=lambda x: -ask_int[x])
    if not bid_modes and not ask_modes:
        return []

    # Merge adjacent (|diff|=1) modes that are mutually exclusive per tick —
    # those are one bot whose continuous offset spans 2 integer cells (a bot
    # using floor / ceil rounding around a non-integer FV produces this
    # exact pattern). E.g. PEPPER outer alternates between -10 and -9
    # depending on FV fraction, but at any single tick only ONE of -10/-9
    # appears for that bot — co-occurrence ≈ 0.
    def _merge_adjacent_mutually_exclusive(modes: list, side: str) -> list:
        if len(modes) < 2:
            return [(m, m) for m in modes]  # (lo_int, hi_int) singleton
        # Build per-tick offset sets for this side.
        per_tick = []
        for r in data.rows:
            if r.fv is None:
                continue
            prices = r.bids if side == "bid" else r.asks
            offs = set(round(p - r.fv) for p in prices)
            per_tick.append(offs)
        # Sort modes by integer value (ascending) to consider adjacency.
        sorted_modes = sorted(modes)
        clusters: list = []  # list of [lo, hi] cluster bounds in offset space
        for m in sorted_modes:
            if clusters and abs(m - clusters[-1][1]) == 1:
                # Check co-occurrence with the cluster's existing range.
                hi = clusters[-1][1]
                co = sum(1 for s in per_tick if hi in s and m in s)
                ind_a = sum(1 for s in per_tick if hi in s)
                ind_b = sum(1 for s in per_tick if m in s)
                # Mutually exclusive if co < 5% of min individual count.
                if co < 0.05 * min(ind_a, ind_b):
                    clusters[-1][1] = m
                    continue
            clusters.append([m, m])
        return [(c[0], c[1]) for c in clusters]

    bid_clusters = _merge_adjacent_mutually_exclusive(bid_modes, "bid")
    ask_clusters = _merge_adjacent_mutually_exclusive(ask_modes, "ask")
    # Replace mode lists with cluster representatives (use the higher-count int as the "peak").
    def _cluster_to_peak(clusters: list, counter: dict) -> list:
        out = []
        for lo, hi in clusters:
            best = max(range(lo, hi + 1), key=lambda x: counter.get(x, 0))
            out.append((best, lo, hi))  # (peak_int, lo_int, hi_int)
        return out
    bid_peaks = sorted(_cluster_to_peak(bid_clusters, bid_int), key=lambda x: -bid_int.get(x[0], 0))
    ask_peaks = sorted(_cluster_to_peak(ask_clusters, ask_int), key=lambda x: -ask_int.get(x[0], 0))
    # Pair clusters by |peak offset| nearest-match (outer first).
    paired: list = []
    used_ask = set()
    for bm_peak, bm_lo, bm_hi in sorted(bid_peaks, key=lambda x: -abs(x[0])):
        best = -1; best_diff = 1e9
        for i, (am_peak, _, _) in enumerate(ask_peaks):
            if i in used_ask: continue
            diff = abs(abs(am_peak) - abs(bm_peak))
            if diff < best_diff:
                best_diff = diff; best = i
        if best >= 0:
            paired.append({"bid": (bm_peak, bm_lo, bm_hi), "ask": ask_peaks[best]})
            used_ask.add(best)
        else:
            paired.append({"bid": (bm_peak, bm_lo, bm_hi), "ask": None})
    for i, ap in enumerate(ask_peaks):
        if i not in used_ask:
            paired.append({"bid": None, "ask": ap})

    layers = []
    for i, p in enumerate(paired):
        bid_t = p["bid"]; ask_t = p["ask"]
        bm = bid_t[0] if bid_t else None
        am = ask_t[0] if ask_t else None
        # Cluster bands: span from low_int - 0.5 to high_int + 0.5 (so the
        # band correctly contains both mutually-exclusive ints when merged).
        bid_band = (bid_t[1] - 0.5, bid_t[2] + 0.5) if bid_t else (0.0, 0.0)
        ask_band = (ask_t[1] - 0.5, ask_t[2] + 0.5) if ask_t else (0.0, 0.0)
        bid_qs = [q for q in quotes if q.side == "bid" and bid_band[0] <= q.offset <= bid_band[1]] if bm is not None else []
        ask_qs = [q for q in quotes if q.side == "ask" and ask_band[0] <= q.offset <= ask_band[1]] if am is not None else []
        # OLS to optionally classify proportional.
        bid_ols = _classify_layer(bid_qs)
        ask_ols = _classify_layer(ask_qs)
        proportional = bid_ols["proportional"] or ask_ols["proportional"]
        k_pool = []
        if bid_ols["proportional"]: k_pool.append(bid_ols["k"])
        if ask_ols["proportional"]: k_pool.append(ask_ols["k"])
        k = sum(k_pool)/len(k_pool) if k_pool else 0.0
        mag = max(abs(bm) if bm is not None else 0, abs(am) if am is not None else 0)
        bid_ols_d = None
        if bid_ols["ols"] is not None:
            o = bid_ols["ols"]
            bid_ols_d = {"alpha": o.alpha, "beta": o.beta, "t_beta": o.t_beta,
                         "p_beta": o.p_beta, "r_squared": o.r_squared, "n": o.n,
                         "se_beta": o.se_beta, "residual_std": o.residual_std}
        ask_ols_d = None
        if ask_ols["ols"] is not None:
            o = ask_ols["ols"]
            ask_ols_d = {"alpha": o.alpha, "beta": o.beta, "t_beta": o.t_beta,
                         "p_beta": o.p_beta, "r_squared": o.r_squared, "n": o.n,
                         "se_beta": o.se_beta, "residual_std": o.residual_std}
        layers.append(DetectedLayer(
            id=f"layer{i+1}",
            name=f"Layer {i+1} ({'outer' if mag > 8 else 'inner' if mag > 4 else 'near-FV'})",
            offset_mag=float(mag),
            offset_type="proportional" if proportional else "fixed",
            k_estimate=k,
            bid_peak_offset=float(bm) if bm is not None else 0.0,
            ask_peak_offset=float(am) if am is not None else 0.0,
            offset_band={"bid": bid_band, "ask": ask_band},
            n_bid=len(bid_qs), n_ask=len(ask_qs),
            bid_ols=bid_ols_d, ask_ols=ask_ols_d,
        ))
    layers.sort(key=lambda L: -L.offset_mag)
    for i, L in enumerate(layers):
        L.id = f"layer{i+1}"
    return layers


def run_stage1(data: FvAndBook, bandwidth: float = 0.0) -> Stage1Result:
    quotes = _extract_quotes(data)
    bid_offsets = [q.offset for q in quotes if q.side == "bid"]
    ask_offsets = [q.offset for q in quotes if q.side == "ask"]

    if len(bid_offsets) < 3 or len(ask_offsets) < 3:
        # Degenerate — return empty result
        empty = K.KdeOut([], [], [], 0.0)
        return Stage1Result(quotes, empty, empty, [], quotes)

    # Primary: integer-mode detection (Prosperity-tailored; better at narrow
    # offsets than KDE peaks, which underdetect when bots are 1-2 integers apart).
    int_layers = _integer_mode_layers(data, quotes)
    if int_layers:
        # Build empty KDE outputs to satisfy the Stage1Result contract — KDE is
        # only consumed by the visualizer chart, not by downstream stages.
        empty_kde = K.KdeOut([], [], [], 0.0)
        # Compute noise quotes (those not captured by any layer band).
        noise = []
        for q in quotes:
            in_layer = False
            for L in int_layers:
                band = L.offset_band["bid"] if q.side == "bid" else L.offset_band["ask"]
                if band[0] <= q.offset <= band[1]:
                    in_layer = True
                    break
            if not in_layer:
                noise.append(q)
        return Stage1Result(quotes, empty_kde, empty_kde, int_layers, noise)

    # Bandwidth defaults to Silverman's; we put a small floor (0.25) so a
    # single bot's offset distribution (which spans up to 1 integer due to
    # FV fractional + integer-price quantization) doesn't get split into
    # multiple peaks.
    if bandwidth <= 0:
        probe = K.kde_peaks(bid_offsets, 400, 0.0)
        if probe.bandwidth < 0.25:
            bandwidth = 0.25
    bid_kde = K.kde_peaks(bid_offsets, 400, bandwidth)
    ask_kde = K.kde_peaks(ask_offsets, 400, bandwidth)

    # Merge KDE peaks that are within 0.5 of each other on the offset axis —
    # a single bot using floor/ceil rounding produces continuous offsets
    # spanning ~1 unit, which the KDE can split into 2 weak peaks. Keep the
    # higher-density peak when collapsing.
    def _merge_close_peaks(kde: K.KdeOut, peaks: list, min_sep: float = 0.5) -> list:
        if not peaks:
            return []
        sorted_peaks = sorted(peaks, key=lambda i: kde.grid[i])
        kept: list = []
        for idx in sorted_peaks:
            if kept and abs(kde.grid[idx] - kde.grid[kept[-1]]) < min_sep:
                # collapse: keep whichever has higher density
                if kde.density[idx] > kde.density[kept[-1]]:
                    kept[-1] = idx
            else:
                kept.append(idx)
        # restore ranking by density (so .peaks[0] is global max)
        kept.sort(key=lambda i: -kde.density[i])
        return kept

    bid_top = _merge_close_peaks(bid_kde, bid_kde.peaks)[:6]
    ask_top = _merge_close_peaks(ask_kde, ask_kde.peaks)[:6]
    bid_bands = _disjoint_bands(bid_kde, bid_top)
    ask_bands = _disjoint_bands(ask_kde, ask_top)
    bid_peak_objs = [
        {"band": bid_bands[i], "mag": abs(bid_kde.grid[bid_top[i]])}
        for i in range(len(bid_top))
    ]
    ask_peak_objs = [
        {"band": ask_bands[i], "mag": abs(ask_kde.grid[ask_top[i]])}
        for i in range(len(ask_top))
    ]
    paired = _pair_peaks(bid_peak_objs, ask_peak_objs)

    bid_quotes = [q for q in quotes if q.side == "bid"]
    ask_quotes = [q for q in quotes if q.side == "ask"]

    layers = []
    for i, p in enumerate(paired):
        bid = p.get("bid"); ask = p.get("ask")
        bid_band = bid["band"] if bid else (0.0, 0.0)
        ask_band = ask["band"] if ask else (0.0, 0.0)
        bid_qs = _quotes_in_band(bid_quotes, bid_band) if bid else []
        ask_qs = _quotes_in_band(ask_quotes, ask_band) if ask else []
        bid_class = _classify_layer(bid_qs)
        ask_class = _classify_layer(ask_qs)
        proportional = bid_class["proportional"] or ask_class["proportional"]
        k_pool = []
        if bid_class["proportional"]:
            k_pool.append(bid_class["k"])
        if ask_class["proportional"]:
            k_pool.append(ask_class["k"])
        k = sum(k_pool) / len(k_pool) if k_pool else 0.0

        sides = (1 if bid else 0) + (1 if ask else 0)
        # NOTE: TS file has a precedence bug here — `bid?.mag ?? 0 + (ask?.mag ?? 0)`
        # parses as `bid?.mag ?? (0 + (ask?.mag ?? 0))`, NOT the intended
        # `(bid?.mag ?? 0) + (ask?.mag ?? 0)`. We replicate the buggy behavior so
        # the CLI matches the visualizer 1:1.
        if bid:
            mag = bid["mag"]
        else:
            mag = (ask["mag"] if ask else 0.0)
        mag_avg = mag / max(1, sides)

        bid_ols_d = None
        if bid_class["ols"] is not None:
            o = bid_class["ols"]
            bid_ols_d = {"alpha": o.alpha, "beta": o.beta, "t_beta": o.t_beta,
                         "p_beta": o.p_beta, "r_squared": o.r_squared, "n": o.n,
                         "se_beta": o.se_beta, "residual_std": o.residual_std}
        ask_ols_d = None
        if ask_class["ols"] is not None:
            o = ask_class["ols"]
            ask_ols_d = {"alpha": o.alpha, "beta": o.beta, "t_beta": o.t_beta,
                         "p_beta": o.p_beta, "r_squared": o.r_squared, "n": o.n,
                         "se_beta": o.se_beta, "residual_std": o.residual_std}

        layers.append(DetectedLayer(
            id=f"layer{i+1}",
            name=f"Layer {i+1} ({'outer' if mag_avg > 8 else 'inner' if mag_avg > 4 else 'near-FV'})",
            offset_mag=mag_avg,
            offset_type="proportional" if proportional else "fixed",
            k_estimate=k,
            bid_peak_offset=bid_kde.grid[bid_kde.peaks[0]] if bid and bid_kde.peaks else 0.0,
            ask_peak_offset=ask_kde.grid[ask_kde.peaks[0]] if ask and ask_kde.peaks else 0.0,
            offset_band={"bid": bid_band, "ask": ask_band},
            n_bid=len(bid_qs), n_ask=len(ask_qs),
            bid_ols=bid_ols_d, ask_ols=ask_ols_d,
        ))

    layers.sort(key=lambda L: -L.offset_mag)
    for i, L in enumerate(layers):
        L.id = f"layer{i+1}"

    noise_quotes = []
    for q in quotes:
        in_layer = False
        for L in layers:
            band = L.offset_band["bid"] if q.side == "bid" else L.offset_band["ask"]
            if band[0] <= q.offset <= band[1]:
                in_layer = True
                break
        if not in_layer:
            noise_quotes.append(q)

    return Stage1Result(quotes, bid_kde, ask_kde, layers, noise_quotes)
