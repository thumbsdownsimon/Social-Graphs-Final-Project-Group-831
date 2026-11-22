"""DeepMoji emotion for every challenge: translate the Danish remark to English, then ask DeepMoji
which of its 64 emoji fit each sentence.

    python -m archetypes.deepmoji              # set up torchMoji, translate, score
    python -m archetypes.deepmoji --limit 200  # quick trial on 200 challenges

Why translate. DeepMoji (Felbo et al. 2017) was trained on 1.2 billion English tweets, so it has
barely seen Danish. We translate each remark with an open Danish->English model
(Helsinki-NLP/opus-mt-da-en, on the GPU if there is one) and score the English. Translation adds
noise, and the model reads tweets, not parliament: treat the result as an instrument to check,
not as ground truth. The group's hand-labeled tone sheet (labeling/challenge_stance.csv) is the
check once the group has labeled it: run_layers.py reports agreement with it.

Setup, as the course page (week 7, Goodies) describes: the PyTorch port torchMoji
(github.com/huggingface/torchMoji) with the weights mirrored on Hugging Face (Uberduck/torchmoji),
plus two one-line patches for Python 3.11+ and PyTorch 2. ensure_torchmoji() does all of it into
third_party/ (not committed), at a pinned commit.

Each remark is split into sentences, each sentence is scored (DeepMoji was trained on short
texts), and the remark's emoji distribution is the mean over its sentences.

Reads  data/challenges.parquet, data-raw/derived/speeches.parquet (the text; see run_layers.py)
Caches data-raw/derived/challenge_translations.parquet (English text, not committed)
Writes data/challenge_emoji.parquet: one row per challenge, 64 emoji probabilities, no text.
"""
import argparse
import json
import re
import subprocess
import sys
import time

import numpy as np
import pandas as pd

from .config import DATA, ROOT

THIRD_PARTY = ROOT / "third_party"
TORCHMOJI = THIRD_PARTY / "torchMoji"
TORCHMOJI_REPO = "https://github.com/huggingface/torchMoji"
TORCHMOJI_COMMIT = "9dd01df645dd84b3645633f55067c0bbcac90011"
WEIGHTS_REPO = "Uberduck/torchmoji"
TRANSLATOR = "Helsinki-NLP/opus-mt-da-en"
SPEECHES = ROOT / "data-raw" / "derived" / "speeches.parquet"
TRANSLATIONS = ROOT / "data-raw" / "derived" / "challenge_translations.parquet"
OUT_FILE = DATA / "challenge_emoji.parquet"
MAXLEN = 50            # DeepMoji tokens per sentence
MAX_SOURCE_TOKENS = 256

# DeepMoji's 64 emoji, in the model's output order (torchMoji examples/text_emojize.py).
EMOJI_ALIASES = (
    ":joy: :unamused: :weary: :sob: :heart_eyes: :pensive: :ok_hand: :blush: :heart: :smirk: "
    ":grin: :notes: :flushed: :100: :sleeping: :relieved: :relaxed: :raised_hands: :two_hearts: :expressionless: "
    ":sweat_smile: :pray: :confused: :kissing_heart: :heartbeat: :neutral_face: :information_desk_person: "
    ":disappointed: :see_no_evil: :tired_face: :v: :sunglasses: :rage: :thumbsup: :cry: :sleepy: :yum: "
    ":triumph: :hand: :mask: :clap: :eyes: :gun: :persevere: :smiling_imp: :sweat: :broken_heart: "
    ":yellow_heart: :musical_note: :speak_no_evil: :wink: :skull: :confounded: :smile: "
    ":stuck_out_tongue_winking_eye: :angry: :no_good: :muscle: :facepunch: :purple_heart: "
    ":sparkling_heart: :blue_heart: :grimacing: :sparkles:"
).split()
EMOJI_NAMES = [a.strip(":") for a in EMOJI_ALIASES]

# Emotion groups, summed like the course's emotion tracks. Our reading of each emoji, not the
# paper's: it is a choice, and it is in one place so it is easy to change. 😂 (named "joy" in the
# model) gets its own group: on Twitter it is laughter, often mocking, so it is neither friendly
# nor hostile here, and it is the model's most common answer for almost any text.
GROUPS = {
    "anger": "rage angry triumph facepunch gun smiling_imp",
    "disapproval": "unamused expressionless neutral_face no_good hand grimacing confused sweat mask see_no_evil speak_no_evil",
    "sadness": "sob cry pensive disappointed broken_heart weary tired_face persevere confounded sleepy",
    "laughter": "joy",
    "happy": "grin smile blush relieved relaxed sweat_smile wink sunglasses yum stuck_out_tongue_winking_eye v ok_hand thumbsup clap raised_hands 100 muscle pray sparkles",
    "love": "heart_eyes heart two_hearts kissing_heart heartbeat yellow_heart purple_heart sparkling_heart blue_heart notes musical_note",
    "other": "flushed sleeping eyes information_desk_person smirk skull",
}
GROUPS = {k: v.split() for k, v in GROUPS.items()}
HOSTILE_GROUPS = ("anger", "disapproval")
FRIENDLY_GROUPS = ("happy", "love")

SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÆØÅ0-9\"»(])")

sys.stdout.reconfigure(encoding="utf-8")


def log(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def check_groups():
    names = [n for group in GROUPS.values() for n in group]
    assert sorted(names) == sorted(EMOJI_NAMES), set(names) ^ set(EMOJI_NAMES)


def ensure_torchmoji():
    """Clone torchMoji at a pinned commit, apply the course's two patches, fetch the weights."""
    if not TORCHMOJI.exists():
        THIRD_PARTY.mkdir(exist_ok=True)
        subprocess.run(["git", "clone", "-q", TORCHMOJI_REPO, str(TORCHMOJI)], check=True)
    subprocess.run(["git", "-C", str(TORCHMOJI), "checkout", "-q", TORCHMOJI_COMMIT], check=True)
    patches = [
        ("torchmoji/tokenizer.py", "RE_TITLES = r'|'.join([r'(?i)' + t for t in TITLES])",
         "RE_TITLES = r'|'.join([r'(?i:' + t + r')' for t in TITLES])"),
        ("torchmoji/lstm.py", "input, batch_sizes = input\n",
         "input, batch_sizes = input.data, input.batch_sizes\n"),
    ]
    for path, old, new in patches:
        file = TORCHMOJI / path
        text = file.read_text(encoding="utf-8")
        if new not in text:
            if old not in text:
                raise RuntimeError(f"torchMoji patch point not found in {path}")
            file.write_text(text.replace(old, new, 1), encoding="utf-8")
    from huggingface_hub import hf_hub_download
    model_dir = TORCHMOJI / "model"
    for name in ("pytorch_model.bin", "vocabulary.json"):
        if not (model_dir / name).exists():
            hf_hub_download(WEIGHTS_REPO, name, local_dir=model_dir)
    if str(TORCHMOJI) not in sys.path:
        sys.path.insert(0, str(TORCHMOJI))


def split_sentences(text):
    return [s for s in SENTENCE_END.split(text or "") if len(s.split()) >= 2]


def challenge_texts(limit=None):
    """Each usable challenge with the challenger's own words, checked by speaker id."""
    edges = pd.read_parquet(DATA / "challenges.parquet")
    edges = edges[edges["challenger_person"].notna()]
    text = pd.read_parquet(SPEECHES, columns=["session", "meeting", "turn", "person", "text"])
    joined = edges.merge(text, on=["session", "meeting", "turn"], how="inner")
    joined = joined[joined["person"] == joined["challenger_person"]]
    joined = joined[["session", "meeting", "turn", "text"]].reset_index(drop=True)
    if limit:
        joined = joined.sample(limit, random_state=831).reset_index(drop=True)
    log(f"{len(joined):,} of {len(edges):,} challenges matched to their text")
    return joined


def translate(sentences, batch_size=48):
    """Danish -> English, longest first so batches pad little."""
    import torch
    from transformers import MarianMTModel, MarianTokenizer
    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = MarianTokenizer.from_pretrained(TRANSLATOR)
    model = MarianMTModel.from_pretrained(TRANSLATOR).to(device).eval()
    if device == "cuda":
        model = model.half()
    order = np.argsort([-len(s) for s in sentences])
    out = [None] * len(sentences)
    start = time.time()
    for i in range(0, len(order), batch_size):
        idx = order[i:i + batch_size]
        batch = tokenizer([sentences[j] for j in idx], return_tensors="pt", padding=True,
                          truncation=True, max_length=MAX_SOURCE_TOKENS).to(device)
        with torch.no_grad():
            generated = model.generate(**batch, num_beams=1, max_length=MAX_SOURCE_TOKENS)
        for j, english in zip(idx, tokenizer.batch_decode(generated, skip_special_tokens=True)):
            out[j] = english
        if (i // batch_size) % 200 == 0:
            done = i + len(idx)
            log(f"translated {done:,} of {len(order):,} sentences ({done / (time.time() - start):.0f}/s, {device})")
    return out


def translations(texts):
    """Sentence-level translations, cached; only new sentences are translated."""
    rows = [(k, n, s) for k, text in enumerate(texts["text"]) for n, s in enumerate(split_sentences(text))]
    frame = pd.DataFrame(rows, columns=["challenge", "sentence", "danish"])
    cache = pd.read_parquet(TRANSLATIONS) if TRANSLATIONS.exists() else pd.DataFrame(columns=["danish", "english"])
    known = dict(zip(cache["danish"], cache["english"]))
    todo = sorted(set(frame["danish"]) - set(known))
    log(f"{len(frame):,} sentences, {len(todo):,} to translate")
    if todo:
        known.update(zip(todo, translate(todo)))
        TRANSLATIONS.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"danish": list(known), "english": list(known.values())}).to_parquet(TRANSLATIONS)
    frame["english"] = frame["danish"].map(known)
    return frame


def emoji_scores(sentences, batch_size=256):
    """64 emoji probabilities per sentence."""
    import torch
    ensure_torchmoji()
    from torchmoji.model_def import torchmoji_emojis
    from torchmoji.sentence_tokenizer import SentenceTokenizer
    vocabulary = json.loads((TORCHMOJI / "model" / "vocabulary.json").read_text(encoding="utf-8"))
    tokenizer = SentenceTokenizer(vocabulary, MAXLEN)
    model = torchmoji_emojis(str(TORCHMOJI / "model" / "pytorch_model.bin")).eval()
    probs = np.zeros((len(sentences), len(EMOJI_NAMES)), dtype=np.float32)
    start = time.time()
    for i in range(0, len(sentences), batch_size):
        tokens, _, _ = tokenizer.tokenize_sentences(sentences[i:i + batch_size])
        empty = tokens.sum(axis=1) == 0
        tokens[empty, 0] = 1  # the model needs one token; such rows are dropped below
        with torch.no_grad():
            p = model(tokens)
        p[empty] = np.nan
        probs[i:i + batch_size] = p
        if (i // batch_size) % 100 == 0:
            done = i + len(tokens)
            log(f"scored {done:,} of {len(sentences):,} sentences ({done / (time.time() - start):.0f}/s)")
    return probs


def add_groups(frame):
    for group, names in GROUPS.items():
        frame[group] = frame[names].sum(axis=1)
    frame["sentiment"] = frame[list(FRIENDLY_GROUPS)].sum(axis=1) - frame[list(HOSTILE_GROUPS)].sum(axis=1)
    return frame


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="score a random sample of this many challenges (a trial run)")
    args = parser.parse_args(argv)
    check_groups()
    ensure_torchmoji()
    texts = challenge_texts(args.limit)
    sentences = translations(texts)
    sentences = sentences[sentences["english"].str.strip().str.len() > 0].reset_index(drop=True)
    probs = emoji_scores(sentences["english"].tolist())
    per_sentence = pd.DataFrame(probs, columns=EMOJI_NAMES)
    per_sentence["challenge"] = sentences["challenge"]
    per_challenge = per_sentence.dropna().groupby("challenge").mean()
    per_challenge["sentences"] = per_sentence.dropna().groupby("challenge").size()
    out = texts.drop(columns="text").join(per_challenge, how="inner")
    out = add_groups(out)
    if args.limit:
        log("trial run: not writing", OUT_FILE.name)
        top = out[EMOJI_NAMES].mean().sort_values(ascending=False).head(10)
        print(top.round(3).to_string())
        print(out[list(GROUPS) + ["sentiment"]].describe().round(3).to_string())
        return out
    out.to_parquet(OUT_FILE)
    log("wrote", OUT_FILE.relative_to(ROOT), f"{len(out):,} challenges")


if __name__ == "__main__":
    main()
