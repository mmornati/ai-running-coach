#!/usr/bin/env python3
"""Narration de la série vidéo « Le Sentier » : script.json -> voix, timing, sous-titres.

Chaque épisode (`docs/video/<dossier>/`) porte un `script.json`, seule source du
découpage et du texte dit :

    {
      "scenes": [
        {"id": "bib", "min": 4.5},
        {"id": "check", "min": 6, "chapter": {"fr": "Le bilan", "en": "The check"},
         "fr": ["Première phrase.", {"text": "Deuxième, pas avant 3 s.", "at": 3.0}],
         "en": ["First sentence.", "Second one."]}
      ]
    }

Pour chaque langue, le script :
  1. synthétise chaque réplique avec Kokoro (ONNX, hors ligne ; FR `ff_siwis`,
     EN `bm_george`), après substitution du lexique de prononciation
     `docs/video/lexicon.json`, complété par `<épisode>/lexicon.json` — les sous-titres gardent le texte d'origine ; une valeur
     `[[…]]` du lexique est une suite de phonèmes IPA passée telle quelle à la voix
     (mots anglais dits « à la française » : trail, /why…) ;
  2. calcule la durée de chaque scène : max(min, attaque + paroles + traîne) ;
  3. écrit `audio/<lang>.m4a` (AAC mono, volume normalisé), `subs.<lang>.vtt`
     et `timing.js` (`window.ARC_TIMING`, lu par docs/video/engine/engine.js).

Moteurs de voix (`--engine`, défaut `kokoro`) — le moteur et la voix retenus sont
notés dans `timing.js`, que `--check` relit :

  - `kokoro`     : local, ONNX, phonèmes IPA du lexique respectés (défaut historique) ;
  - `azure`      : Azure AI Speech (palier gratuit F0 : 500 000 caractères/mois), `AZURE_SPEECH_KEY` +
                   `AZURE_SPEECH_REGION` ; IPA du lexique passés en SSML `<phoneme>` ;
  - `edge`       : mêmes voix neuronales Microsoft sans compte (paquet `edge-tts`,
                   point d'accès non officiel — pour écouter, pas pour la série) ;
  - `chatterbox` : local (Resemble AI, MIT), voix clonable (`--voice fr=ref.wav`) ;
  - `kyutai`     : local, MLX (Apple Silicon), modèle `kyutai/tts-1.6b-en_fr`.

`edge`, `chatterbox` et `kyutai` ne lisent pas l'IPA : une entrée `[[…]]` du lexique
y est remplacée par le mot d'origine, sauf entrée dédiée sous la clé `<langue>@<moteur>`
du lexique (ex. `"fr@kyutai"`), qui surcharge `<langue>` pour ce seul moteur. Les
moteurs lourds tournent dans leur propre environnement `uv` (sous-processus) : la
commande reste `uv run --with kokoro-onnx --with soundfile scripts/video_narration.py`.

Comparer à l'oreille sans toucher à la série : `--sample <scène> --out <dossier>`
écrit une piste par moteur/langue pour la scène donnée d'UN épisode, ex.

    uv run --with kokoro-onnx --with soundfile scripts/video_narration.py styles-coaching \
        --sample voices --engine kyutai --out /tmp/voix

Les répliques déjà synthétisées sont mises en cache
(`~/.cache/arc-video/tts/<empreinte>.wav`) : relancer ne refait que ce qui a changé.

Prérequis : `ffmpeg`, `uv`, et le modèle Kokoro dans `~/.cache/kokoro-onnx/`
(`kokoro-v1.0.onnx`, `voices-v1.0.bin`, release « model-files-v1.0 » de
github.com/thewh1teagle/kokoro-onnx). Rien n'est installé dans le projet :

    uv run --with kokoro-onnx --with soundfile scripts/video_narration.py            # tous les épisodes
    uv run --with kokoro-onnx --with soundfile scripts/video_narration.py garde-fous --lang fr
    python3 scripts/video_narration.py --check     # stdlib seule : timing.js à jour ?

`--check` (utilisé par le lint du palier B) ne synthétise rien : il vérifie que
chaque `timing.js` correspond au `script.json` courant et que les fichiers audio
existent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VIDEO = REPO / "docs" / "video"
LEXICON = VIDEO / "lexicon.json"
MODEL_DIR = Path.home() / ".cache" / "kokoro-onnx"
CACHE = Path.home() / ".cache" / "arc-video" / "tts"
SR = 24000

ENGINES = {
    "kokoro": {
        "fr": {"voice": "ff_siwis", "lang": "fr-fr", "speed": 1.0},
        "en": {"voice": "bm_george", "lang": "en-gb", "speed": 1.0},
    },
    "azure": {
        "fr": {"voice": "fr-FR-RemyMultilingualNeural", "lang": "fr-FR", "rate": "+0%"},
        "en": {"voice": "en-US-AndrewMultilingualNeural", "lang": "en-US", "rate": "+0%"},
    },
    "edge": {
        "fr": {"voice": "fr-FR-RemyMultilingualNeural", "rate": "+0%"},
        "en": {"voice": "en-US-AndrewMultilingualNeural", "rate": "+0%"},
    },
    "chatterbox": {
        "fr": {"voice": "", "exaggeration": 0.5, "cfg_weight": 0.5},
        "en": {"voice": "", "exaggeration": 0.5, "cfg_weight": 0.5},
    },
    "kyutai": {
        "fr": {"voice": "unmute-prod-website/fabieng-enhanced-v2.wav"},
        "en": {"voice": "unmute-prod-website/ex04_narration_longform_00001.wav"},
    },
}
VOICES = ENGINES["kokoro"]  # langues de la série ; voix par défaut
IPA_ENGINES = {"kokoro", "azure"}
# moteurs qui partagent les mêmes voix : une entrée `<langue>@<famille>` du lexique vaut pour tous
LEXICON_FAMILY = {"edge": "microsoft", "azure": "microsoft"}
LEAD, GAP, TAIL = 0.5, 0.35, 0.6


def episodes() -> list[Path]:
    """Dossiers d'épisode : ceux qui portent un script.json."""
    return sorted(p.parent for p in VIDEO.glob("*/script.json"))


def load_script(ep: Path) -> dict:
    data = json.loads((ep / "script.json").read_text(encoding="utf-8"))
    ids = [s["id"] for s in data["scenes"]]
    if len(ids) != len(set(ids)):
        raise SystemExit(f"{ep.name}/script.json : identifiants de scène en double")
    return data


def cues_of(scene: dict, lang: str) -> list[dict]:
    out = []
    for c in scene.get(lang, []):
        out.append({"text": c, "at": None} if isinstance(c, str) else {"text": c["text"], "at": c.get("at")})
    return out


def script_digest(ep: Path, data: dict, lang: str, engine: str = "kokoro", cfg: dict | None = None) -> str:
    """Empreinte de ce qui détermine le timing d'une langue (texte, minima, moteur, voix, lexique)."""
    cfg = ENGINES[engine][lang] if cfg is None else cfg
    lex = lexicon(ep, lang, engine)
    payload = {
        # kokoro garde la forme d'origine : les timing.js existants restent valides
        "voice": cfg if engine == "kokoro" else {"engine": engine, **cfg}, "lex": lex, "lead": LEAD, "gap": GAP, "tail": TAIL,
        "scenes": [{"id": s["id"], "min": s.get("min"), "lead": s.get("lead"), "tail": s.get("tail"),
                    "cues": cues_of(s, lang)} for s in data["scenes"]],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def lexicon(ep: Path, lang: str, engine: str = "kokoro") -> dict:
    """Lexique commun (docs/video/lexicon.json) complété/surchargé par celui de l'épisode ;
    `<langue>@<famille>` puis `<langue>@<moteur>` surchargent `<langue>` pour ce moteur."""
    lex = {}
    keys = [lang] + [f"{lang}@{x}" for x in (LEXICON_FAMILY.get(engine), engine) if x]
    for key in keys:
        for f in (LEXICON, ep / "lexicon.json"):
            if f.exists():
                lex.update(json.loads(f.read_text(encoding="utf-8")).get(key, {}))
    return {k: v for k, v in lex.items() if not k.startswith("_")}  # `_doc` : note, pas un mot


def pronounce(s: str, lang: str, ep: Path, engine: str = "kokoro") -> str:
    """Applique le lexique de prononciation (mots entiers, casse exacte).

    kokoro reçoit `[[ipa]]` ; azure `[[ipa|mot]]` (SSML `<phoneme>` garde le mot) ;
    les moteurs sans IPA lisent le mot d'origine."""
    lex = {}
    for src, val in lexicon(ep, lang, engine).items():
        m = re.fullmatch(r"\[\[(.+)\]\]", val)
        if m and engine == "azure":
            val = f"[[{m.group(1)}|{src}]]"
        elif m and engine not in IPA_ENGINES:
            val = src
        lex[src] = val
    if not lex:
        return s
    # une seule passe, le plus long d'abord : un remplacement n'est jamais relu
    alt = "|".join(re.escape(k) for k in sorted(lex, key=len, reverse=True))
    return re.sub(rf"(?<![\w/])(?:{alt})(?!\w)", lambda m: lex[m.group(0)], s)


def cache_path(engine: str, spoken: str, cfg: dict) -> Path:
    # clé kokoro inchangée : le cache existant reste valable
    tag = ["remove-flags", "ipa"] if engine == "kokoro" else [engine]
    return CACHE / f"{hashlib.sha256(json.dumps([spoken, cfg, *tag], sort_keys=True).encode()).hexdigest()[:24]}.wav"


def to_pcm24k(src: Path, dst: Path) -> None:
    """Tout fichier audio -> WAV mono 16 bits 24 kHz (format du cache)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ar", str(SR), "-ac", "1",
                    "-sample_fmt", "s16", str(tmp)], check=True)
    tmp.replace(dst)


def uv_run(deps: list[str], args: list[str], python: str = "3.12") -> None:
    """Moteur lourd dans son propre environnement uv (rien d'installé dans le projet)."""
    if not shutil.which("uv"):
        raise SystemExit("uv introuvable dans le PATH (brew install uv).")
    cmd = ["uv", "run", "--quiet", "--no-project", "--python", python]
    for d in deps:
        cmd += ["--with", d]
    subprocess.run(cmd + args, check=True)


class Engine:
    """Moteur de synthèse : `render` remplit le cache pour une liste de répliques."""

    name = ""

    def __init__(self, voices: dict):
        self.voices = voices  # {lang: cfg}

    def spoken(self, text: str, lang: str, ep: Path) -> str:
        return pronounce(text, lang, ep, self.name)

    def say(self, text: str, lang: str, ep: Path) -> list[int]:
        self.render([(text, lang, ep)])
        return read_wav(cache_path(self.name, self.spoken(text, lang, ep), self.voices[lang]))

    def render(self, items: list[tuple[str, str, Path]]) -> None:
        todo = {}
        for text, lang, ep in items:
            sp, cfg = self.spoken(text, lang, ep), self.voices[lang]
            path = cache_path(self.name, sp, cfg)
            if not path.exists():
                todo[path] = (sp, lang, cfg)
        if todo:
            print(f"  {self.name} : {len(todo)} réplique(s) à synthétiser", file=sys.stderr)
            CACHE.mkdir(parents=True, exist_ok=True)
            self.synth(todo)

    def synth(self, todo: dict) -> None:
        raise NotImplementedError


class KokoroEngine(Engine):
    """Synthèse Kokoro locale (ONNX), phonèmes IPA du lexique respectés."""

    name = "kokoro"

    def __init__(self, voices: dict):
        super().__init__(voices)
        self._k = None

    def _model(self):
        if self._k is None:
            try:
                from kokoro_onnx import Kokoro
            except ImportError:
                raise SystemExit("kokoro-onnx manquant : uv run --with kokoro-onnx --with soundfile scripts/video_narration.py")
            onnx, voices = MODEL_DIR / "kokoro-v1.0.onnx", MODEL_DIR / "voices-v1.0.bin"
            if not onnx.exists() or not voices.exists():
                raise SystemExit(f"Modèle Kokoro absent de {MODEL_DIR} (voir l'en-tête de ce script).")
            self._k = Kokoro(str(onnx), str(voices))
        return self._k

    def phonemes(self, text: str, lang: str) -> str:
        """Phonèmes espeak SANS drapeaux de changement de langue.

        kokoro-onnx garde les drapeaux par défaut (`(en)kˈoʊtʃ(fr)`) puis ne filtre que
        les parenthèses : la voix française lit alors « en … fr » autour de chaque mot
        anglais (« coach », « slash »). `remove-flags` garde la prononciation anglaise
        du mot, sans les drapeaux."""
        import phonemizer
        from kokoro_onnx.tokenizer import Tokenizer, _espeak_lock
        tok = self._model().tokenizer
        out = []
        # `[[…]]` = phonèmes bruts du lexique, passés tels quels à la voix
        for i, part in enumerate(re.split(r"\[\[(.+?)\]\]", text)):
            if i % 2:
                out.append(part)
            elif part.strip():
                with _espeak_lock:
                    out.append(phonemizer.phonemize(Tokenizer.normalize_text(part), lang, preserve_punctuation=True,
                                                    with_stress=True, language_switch="remove-flags").strip())
            if part[-1:].isspace() or part[:1].isspace():
                out.append(" ")
        ph = re.sub(r"\s+", " ", " ".join(out))
        return "".join(p for p in ph if p in tok.vocab).strip()

    def synth(self, todo: dict) -> None:
        import soundfile as sf
        for path, (spoken, _lang, v) in todo.items():
            samples, sr = self._model().create(self.phonemes(spoken, v["lang"]), voice=v["voice"], speed=v["speed"],
                                               lang=v["lang"], is_phonemes=True)
            if sr != SR:
                raise SystemExit(f"Fréquence inattendue {sr} Hz")
            sf.write(path, samples, SR, subtype="PCM_16")




class AzureEngine(Engine):
    """Azure AI Speech (REST, stdlib) ; `[[ipa|mot]]` -> SSML `<phoneme alphabet="ipa">`."""

    name = "azure"

    def ssml(self, spoken: str, v: dict) -> str:
        from xml.sax.saxutils import escape, quoteattr
        body = []
        for i, part in enumerate(re.split(r"\[\[(.+?)\]\]", spoken)):
            if i % 2:
                ipa, _, word = part.partition("|")
                body.append(f'<phoneme alphabet="ipa" ph={quoteattr(ipa)}>{escape(word or ipa)}</phoneme>')
            else:
                body.append(escape(part))
        return (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{v["lang"]}">'
                f'<voice name="{v["voice"]}"><prosody rate="{v.get("rate", "+0%")}">{"".join(body)}</prosody>'
                f'</voice></speak>')

    def synth(self, todo: dict) -> None:
        import os
        import time
        import urllib.error
        import urllib.request
        key, region = os.environ.get("AZURE_SPEECH_KEY"), os.environ.get("AZURE_SPEECH_REGION")
        if not key or not region:
            raise SystemExit("Moteur azure : définir AZURE_SPEECH_KEY et AZURE_SPEECH_REGION (palier gratuit F0).")
        for path, (spoken, _lang, v) in todo.items():
            req = urllib.request.Request(
                f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
                data=self.ssml(spoken, v).encode("utf-8"),
                headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/ssml+xml",
                         "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm", "User-Agent": "arc-video"})
            for attempt in range(6):
                try:
                    with urllib.request.urlopen(req, timeout=60) as r:
                        audio = r.read()
                    break
                except urllib.error.HTTPError as e:
                    # palier gratuit F0 : ~20 requêtes par minute -> 429, on attend et on recommence
                    if e.code == 429 and attempt < 5:
                        time.sleep(float(e.headers.get("Retry-After") or 15))
                        continue
                    raise SystemExit(f"Azure : HTTP {e.code} pour « {spoken[:60]} » — {e.read()[:200]!r}")
            with tempfile.TemporaryDirectory() as tmp:
                raw = Path(tmp) / "a.wav"
                raw.write_bytes(audio)
                to_pcm24k(raw, path)


EDGE_PROG = """
import asyncio, json, sys, edge_tts
async def main():
    for j in json.load(open(sys.argv[1])):
        for attempt in range(5):
            try:
                await edge_tts.Communicate(j["text"], j["voice"], rate=j["rate"]).save(j["out"])
                break
            except Exception as e:
                if attempt == 4:
                    raise
                print(f"edge-tts : nouvel essai ({e})", file=sys.stderr)
                await asyncio.sleep(2 ** attempt)
asyncio.run(main())
"""


class EdgeEngine(Engine):
    """Voix neuronales Microsoft via `edge-tts` (sans compte, point d'accès non officiel)."""

    name = "edge"

    def synth(self, todo: dict) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs = [{"text": sp, "voice": v["voice"], "rate": v.get("rate", "+0%"), "out": str(Path(tmp) / f"{i}.mp3")}
                    for i, (sp, _lang, v) in enumerate(todo.values())]
            (Path(tmp) / "jobs.json").write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
            uv_run(["edge-tts"], ["python", "-c", EDGE_PROG, str(Path(tmp) / "jobs.json")])
            for path, j in zip(todo, jobs):
                to_pcm24k(Path(j["out"]), path)


CHATTERBOX_PROG = """
import json, sys, torch, soundfile as sf
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
dev = "mps" if torch.backends.mps.is_available() else "cpu"
_load = torch.load  # points de contrôle sauvés sur CUDA : charger sur CPU, puis déplacer
torch.load = lambda *a, **k: _load(*a, **{**k, "map_location": "cpu"})
model = ChatterboxMultilingualTTS.from_pretrained(device=torch.device(dev))
for j in json.load(open(sys.argv[1])):
    wav = model.generate(j["text"], language_id=j["lang"], audio_prompt_path=j["voice"] or None,
                         exaggeration=j["exaggeration"], cfg_weight=j["cfg_weight"])
    sf.write(j["out"], wav.squeeze(0).cpu().numpy(), model.sr)
"""


class ChatterboxEngine(Engine):
    """Chatterbox Multilingual (Resemble AI, MIT), local ; `voice` = WAV de référence à cloner, ou vide."""

    name = "chatterbox"

    def synth(self, todo: dict) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs = [{"text": sp, "lang": lang, "out": str(Path(tmp) / f"{i}.wav"), "voice": v["voice"],
                     "exaggeration": v["exaggeration"], "cfg_weight": v["cfg_weight"]}
                    for i, (sp, lang, v) in enumerate(todo.values())]
            (Path(tmp) / "jobs.json").write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
            uv_run(["chatterbox-tts", "setuptools<81"], ["python", "-c", CHATTERBOX_PROG, str(Path(tmp) / "jobs.json")], python="3.11")
            for path, j in zip(todo, jobs):
                to_pcm24k(Path(j["out"]), path)


class KyutaiEngine(Engine):
    """Kyutai TTS 1.6B en/fr via moshi-mlx (Apple Silicon) ; `voice` = fichier de kyutai/tts-voices."""

    name = "kyutai"

    def synth(self, todo: dict) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reqs = [{"turns": [sp], "voices": [v["voice"]], "id": f"r{i}"}
                    for i, (sp, _lang, v) in enumerate(todo.values())]
            jsonl = Path(tmp) / "req.jsonl"
            jsonl.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in reqs), encoding="utf-8")
            uv_run(["moshi-mlx"], ["python", "-m", "moshi_mlx.run_tts", "--only-wav", "--quantize", "8",
                                   "--out-folder", tmp, str(jsonl)])
            for path, r in zip(todo, reqs):
                to_pcm24k(Path(tmp) / f"{r['id']}.wav", path)


ENGINE_CLASSES = {c.name: c for c in (KokoroEngine, AzureEngine, EdgeEngine, ChatterboxEngine, KyutaiEngine)}


def make_engine(name: str, overrides: dict | None = None) -> Engine:
    voices = {lang: dict(cfg) for lang, cfg in ENGINES[name].items()}
    for lang, voice in (overrides or {}).items():
        voices[lang]["voice"] = voice
    return ENGINE_CLASSES[name](voices)


def read_wav(path: Path) -> list[int]:
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return list(memoryview(raw).cast("h"))


def write_wav(path: Path, pcm: "array") -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def vtt_time(s: float) -> str:
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{sec:06.3f}"


def build_lang(ep: Path, data: dict, lang: str, voice: Engine) -> dict:
    from array import array
    voice.render([(c["text"], lang, ep) for sc in data["scenes"] for c in cues_of(sc, lang)])
    plan, start, clips = [], 0.0, []
    for sc in data["scenes"]:
        lead = sc.get("lead", LEAD)
        cur, cues = lead, []
        for c in cues_of(sc, lang):
            pcm = voice.say(c["text"], lang, ep)
            if c["at"] is not None:
                cur = max(cur, float(c["at"]))
            dur = len(pcm) / SR
            cues.append({"s": round(cur, 3), "e": round(cur + dur, 3), "text": c["text"]})
            clips.append((start + cur, pcm))
            cur += dur + GAP
        speech_end = (cues[-1]["e"] if cues else 0) + sc.get("tail", TAIL)
        d = round(max(float(sc.get("min", 3.0)), speech_end), 3)
        item = {"id": sc["id"], "start": round(start, 3), "d": d, "cues": cues}
        if sc.get("chapter"):
            item["chapter"] = sc["chapter"][lang] if isinstance(sc["chapter"], dict) else sc["chapter"]
        plan.append(item)
        start += d
    duration = round(start, 3)

    # piste audio complète, alignée sur la timeline
    pcm = array("h", bytes(2 * (int(duration * SR) + SR)))
    for at, clip in clips:
        i0 = int(at * SR)
        for j, v in enumerate(clip):
            if i0 + j < len(pcm):
                pcm[i0 + j] = v
    (ep / "audio").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "voice.wav"
        write_wav(wav, pcm)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-t", f"{duration:.3f}",
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "1",
             "-c:a", "aac", "-b:a", "48k", "-movflags", "+faststart", str(Path(tmp) / f"{lang}.m4a")],
            check=True,
        )
        # remplacement atomique : deux générations simultanées ne corrompent jamais la piste publiée
        shutil.move(str(Path(tmp) / f"{lang}.m4a"), str(ep / "audio" / f"{lang}.m4a"))
    vtt = ["WEBVTT", ""]
    n = 0
    for sc in plan:
        for c in sc["cues"]:
            n += 1
            vtt += [str(n), f"{vtt_time(sc['start'] + c['s'])} --> {vtt_time(sc['start'] + c['e'] + 0.25)}", c["text"], ""]
    (ep / f"subs.{lang}.vtt").write_text("\n".join(vtt), encoding="utf-8")
    out = {"digest": script_digest(ep, data, lang, voice.name, voice.voices[lang]), "duration": duration, "scenes": plan}
    if voice.name != "kokoro" or voice.voices[lang] != ENGINES["kokoro"][lang]:
        out["engine"], out["voice"] = voice.name, voice.voices[lang]
    return out


def build_sample(ep: Path, data: dict, scene_id: str, lang: str, voice: Engine, out_dir: Path) -> Path:
    """Une scène, une langue, un moteur -> `<out>/<épisode>_<scène>_<moteur>_<voix>_<lang>.m4a`."""
    from array import array
    sc = next((s for s in data["scenes"] if s["id"] == scene_id), None)
    if sc is None:
        raise SystemExit(f"Scène inconnue : {scene_id} (connues : {', '.join(s['id'] for s in data['scenes'])})")
    cues = cues_of(sc, lang)
    if not cues:
        raise SystemExit(f"{ep.name}/{scene_id} : aucune réplique en {lang}")
    voice.render([(c["text"], lang, ep) for c in cues])
    pcm, gap = array("h"), array("h", bytes(2 * int(GAP * SR)))
    for c in cues:
        pcm += array("h", voice.say(c["text"], lang, ep)) + gap
    slug = re.sub(r"[^\w-]+", "-", Path(voice.voices[lang]["voice"] or "defaut").stem).strip("-")
    dst = out_dir / f"{ep.name}_{scene_id}_{voice.name}_{slug}_{lang}.m4a"
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "s.wav"
        write_wav(wav, pcm)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                        "-ar", "48000", "-ac", "1", "-c:a", "aac", "-b:a", "96k", str(dst)], check=True)
    return dst


TIMING_PREFIX = "/* Généré par scripts/video_narration.py — ne pas éditer. */\nwindow.ARC_TIMING = "


def read_timing(ep: Path) -> dict:
    p = ep / "timing.js"
    if not p.exists():
        return {}
    txt = p.read_text(encoding="utf-8")
    body = txt[len(TIMING_PREFIX):].rstrip().rstrip(";") if txt.startswith(TIMING_PREFIX) else "{}"
    return json.loads(body)


def write_timing(ep: Path, timing: dict) -> None:
    (ep / "timing.js").write_text(TIMING_PREFIX + json.dumps(timing, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")


def check(eps: list[Path]) -> int:
    bad = []
    for ep in eps:
        data, timing = load_script(ep), read_timing(ep)
        for lang in VOICES:
            t = timing.get(lang)
            if not t:
                bad.append(f"{ep.name} [{lang}] : timing absent")
            elif t.get("digest") != script_digest(ep, data, lang, t.get("engine", "kokoro"), t.get("voice")):
                bad.append(f"{ep.name} [{lang}] : timing périmé (script.json ou lexique modifié)")
            if not (ep / "audio" / f"{lang}.m4a").exists():
                bad.append(f"{ep.name} [{lang}] : audio/{lang}.m4a absent")
    for b in bad:
        print(b, file=sys.stderr)
    if bad:
        print("Régénérer : uv run --with kokoro-onnx --with soundfile scripts/video_narration.py", file=sys.stderr)
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("episodes", nargs="*", help="dossiers d'épisode (défaut : tous)")
    ap.add_argument("--lang", choices=sorted(VOICES), action="append", help="langue (répétable, défaut : toutes)")
    ap.add_argument("--check", action="store_true", help="vérifie seulement que timing.js et l'audio sont à jour")
    ap.add_argument("--engine", choices=sorted(ENGINES), default="kokoro", help="moteur de voix (défaut : kokoro)")
    ap.add_argument("--voice", action="append", default=[], metavar="LANG=VOIX",
                    help="remplace la voix du moteur pour une langue (répétable), ex. fr=fr-FR-DeniseNeural")
    ap.add_argument("--sample", metavar="SCENE", help="n'écrit qu'un extrait de cette scène dans --out (série intacte)")
    ap.add_argument("--out", type=Path, help="dossier des extraits (--sample)")
    args = ap.parse_args(argv)
    overrides = {}
    for v in args.voice:
        lang, sep, name = v.partition("=")
        if not sep or lang not in VOICES:
            raise SystemExit(f"--voice attend LANG=VOIX avec LANG dans {sorted(VOICES)} : {v}")
        overrides[lang] = name
    if args.sample and (not args.out or len(args.episodes) != 1):
        raise SystemExit("--sample exige un seul épisode et --out <dossier>")

    known = {p.name: p for p in episodes()}
    for name in args.episodes:
        if name not in known:
            raise SystemExit(f"Épisode inconnu : {name} (connus : {', '.join(sorted(known))})")
    eps = [known[n] for n in args.episodes] if args.episodes else list(known.values())
    if args.check:
        return check(eps)
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg introuvable dans le PATH (brew install ffmpeg).")
    voice = make_engine(args.engine, overrides)
    if args.sample:
        data = load_script(eps[0])
        for lang in args.lang or sorted(VOICES):
            print(build_sample(eps[0], data, args.sample, lang, voice, args.out))
        return 0
    for ep in eps:
        data, timing = load_script(ep), read_timing(ep)
        for lang in args.lang or sorted(VOICES):
            timing[lang] = build_lang(ep, data, lang, voice)
            print(f"{ep.name} [{lang}] {timing[lang]['duration']:.1f} s")
        write_timing(ep, timing)
    return 0


if __name__ == "__main__":
    sys.exit(main())
