"""Every constant the archetype pipeline uses, in one place."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = DATA / "results"
OUT = DATA / "archetypes"

SEED = 831
N_SHUFFLES = 500

# Party codes that are not parties. UFG (uden for grupperne, independent) is kept: leaving
# for UFG is a defection, but UFG has no bloc.
NOT_A_PARTY = {"Pause", "MødeSlut"}
INDEPENDENT = "UFG"

# Same party under a new code: not a switch.
RENAMES = {"TF": "T"}

# An assumption, not data: RV and M in particular have moved between camps. The
# government/opposition side (from governments.json) is the measure we trust more.
BLOC = {
    **{p: "red" for p in ["S", "SF", "RV", "EL", "ALT", "FG"]},
    **{p: "blue" for p in ["V", "KF", "DF", "LA", "NB", "DD", "BP", "KD"]},
    "M": "centre",
    **{p: "north_atlantic" for p in ["IA", "SIU", "SP", "T", "JF", "NQ", "N"]},
}
MAIN_BLOCS = {"red", "blue"}

# Party runs: a label must hold for this many consecutive non-minister appearances to count.
MIN_RUN = 3

# Roles: a member needs this many challenges (made + received) in a window to be ranked.
MIN_EDGES = 15
ROLE = {
    "top": 0.80,            # "top 20%" percentile cut
    "upper_half": 0.50,
    "attack_balance": 1 / 3,
    "z": 2.0,
    "cross_side_share": 0.8,
    "own_side_share": 0.3,
    "min_minister_in": 10,  # challenges received as minister before ranking as a minister rod
}
