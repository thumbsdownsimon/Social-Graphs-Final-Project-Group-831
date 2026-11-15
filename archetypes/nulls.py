"""Is a member's targeting more than chance? Shuffle one side of the edges and compare.

Out-side measures (whom a member's challenges hit) shuffle the floor holders; in-side
measures (who challenges a member) shuffle the challengers. Shuffling one side keeps every
member's number of challenges made and received, which is a directed configuration model. With
group="debate" (the default) the shuffle stays inside one debate, so the null also keeps who
was present in each debate: a member who only joins immigration debates is compared with
the other people in those debates, not with the whole parliament.

Self-loops the shuffle creates are removed from both count and total.
"""
import warnings

import numpy as np
import pandas as pd

from .config import N_SHUFFLES, SEED
from .data import own_side

OUT_MEASURES = ["cross_side", "own_side", "own_party", "at_government", "cross_bloc"]
IN_MEASURES = ["in_cross_side"]


def permute_within(codes, rng):
    """A permutation that only moves positions within equal codes."""
    order = np.argsort(codes, kind="stable")
    shuffled = np.lexsort((rng.random(len(codes)), codes))
    perm = np.empty(len(codes), dtype=int)
    perm[order] = shuffled
    return perm


def _indicators(e, fixed, moved):
    """Numerator and denominator indicators for every measure, with `moved` the shuffled side.

    fixed/moved are dicts of arrays: person, party, gov, bloc_main (bool), bloc.
    """
    not_self = fixed["person"] != moved["person"]
    both_main = fixed["bloc_main"] & moved["bloc_main"]
    allies = own_side(fixed["party"], moved["party"], fixed["gov"], moved["gov"], fixed["bloc"], moved["bloc"])
    return {
        "cross_side": ((fixed["gov"] != moved["gov"]) & not_self, not_self),
        "own_side": (allies & not_self, not_self),
        "own_party": ((fixed["party"] == moved["party"]) & not_self, not_self),
        "at_government": (moved["gov"] & not_self, not_self),
        "cross_bloc": ((fixed["bloc"] != moved["bloc"]) & both_main & not_self, both_main & not_self),
    }


def _side(e, prefix, person_col):
    bloc = e[f"{prefix}_bloc"].fillna("").to_numpy(dtype=object)
    return {"person": e[person_col].to_numpy(), "party": e[f"{prefix}_party"].to_numpy(dtype=object),
            "gov": e[f"{prefix}_gov"].to_numpy(bool), "bloc": bloc,
            "bloc_main": np.isin(bloc, ["red", "blue"])}


def _take(side, perm):
    return {k: v[perm] for k, v in side.items()}


def _shares(num, den, who, n_people):
    top = np.bincount(who, weights=num.astype(float), minlength=n_people)
    bottom = np.bincount(who, weights=den.astype(float), minlength=n_people)
    with np.errstate(invalid="ignore", divide="ignore"):
        return top / bottom


def member_nulls(edges, n=N_SHUFFLES, group="debate", seed=SEED):
    """Observed share, null mean, z and one-sided p (higher than chance) per member and measure."""
    rng = np.random.default_rng(seed)
    people = np.unique(np.concatenate([edges["challenger"].to_numpy(), edges["floor"].to_numpy()]))
    index = {p: i for i, p in enumerate(people)}
    c_idx = edges["challenger"].map(index).to_numpy()
    f_idx = edges["floor"].map(index).to_numpy()
    codes = (pd.factorize(edges[group])[0] if group else np.zeros(len(edges), dtype=int))
    challenger, floor = _side(edges, "c", "challenger"), _side(edges, "f", "floor")
    size = len(people)

    def out_shares(moved_floor):
        ind = _indicators(edges, challenger, moved_floor)
        return {m: _shares(*ind[m], c_idx, size) for m in OUT_MEASURES}

    def in_shares(moved_challenger):
        ind = _indicators(edges, floor, moved_challenger)
        return {"in_cross_side": _shares(*ind["cross_side"], f_idx, size)}

    observed = {**out_shares(floor), **in_shares(challenger)}
    null = {m: np.empty((n, size)) for m in observed}
    for i in range(n):
        shuffled_out = out_shares(_take(floor, permute_within(codes, rng)))
        # The in-side shuffle moves challengers, but who is credited (f_idx) stays put.
        shuffled_in = in_shares(_take(challenger, permute_within(codes, rng)))
        for m, v in {**shuffled_out, **shuffled_in}.items():
            null[m][i] = v

    table = pd.DataFrame({"person": people})
    for m, obs in observed.items():
        sims = null[m]
        # Members with no edges of a kind have all-NaN columns; their stats are NaN, as intended.
        with warnings.catch_warnings(), np.errstate(invalid="ignore", divide="ignore"):
            warnings.simplefilter("ignore", RuntimeWarning)
            mean = np.nanmean(sims, axis=0) if n else np.full(size, np.nan)
            sd = np.nanstd(sims, axis=0) if n else np.full(size, np.nan)
            z = np.where(sd > 0, (obs - mean) / sd, np.nan)
            higher = (np.nansum(sims >= obs[None, :] - 1e-12, axis=0) + 1) / (np.sum(~np.isnan(sims), axis=0) + 1)
        table[f"null_{m}"] = mean
        table[f"z_{m}"] = z
        table[f"p_{m}"] = np.where(np.isnan(obs), np.nan, higher)
    return table
