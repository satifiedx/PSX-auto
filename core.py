"""
PSX Sample Forge core: audio prep, VAG encoding (via psxavenc) and SPU-ADPCM decoding.
No GUI imports here, so it can be used from the CLI or as a library.
"""
import os
import sys
import shutil
import struct
import subprocess
import tempfile
import wave

import numpy as np
import soundfile as sf
import soxr

# PSX SPU processes audio in ADPCM blocks of 28 samples (16 bytes each)
SPU_BLOCK_SAMPLES = 28
SPU_BLOCK_BYTES = 16
VAG_HEADER_SIZE = 48
DEFAULT_RATE = 22050
MAX_RATE = 44100
# Common rates: 44100 = SPU max, 22050 = classic, 11025 = crunchy lo-fi
RATE_PRESETS = (44100, 32000, 22050, 16000, 11025, 8000)

AUDIO_EXTENSIONS = (".wav", ".flac", ".ogg", ".oga", ".opus", ".mp3", ".aif", ".aiff", ".aifc", ".w64", ".caf")

# SPU-ADPCM prediction filter coefficients (x/64)
_FILTER_POS = (0, 60, 115, 98, 122)
_FILTER_NEG = (0, 0, -52, -55, -60)

# VAG block flags
FLAG_END = 0x01
FLAG_REPEAT = 0x02
FLAG_START = 0x04


class ForgeError(Exception):
    """Conversion error with a user friendly message."""


def get_resource_path(relative_path):
    """Absolute path to a resource, works both from source and from a PyInstaller exe."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def find_encoder():
    """Locate psxavenc: bundled bin/ first, then PATH."""
    name = "psxavenc.exe" if os.name == "nt" else "psxavenc"
    bundled = get_resource_path(os.path.join("bin", name))
    if os.path.isfile(bundled):
        return bundled
    return shutil.which("psxavenc")


def collect_audio_files(paths):
    """Expand files and folders (recursively) into a sorted list of supported audio files."""
    result = []
    for path in paths:
        if os.path.isdir(path):
            for root, _, files in os.walk(path):
                # Skip our own decoded exports so re-running on a folder doesn't snowball
                result.extend(os.path.join(root, f) for f in sorted(files)
                              if f.lower().endswith(AUDIO_EXTENSIONS) and not f.lower().endswith(".psx.wav"))
        elif os.path.isfile(path) and path.lower().endswith(AUDIO_EXTENSIONS):
            result.append(path)
    # Keep order, drop duplicates
    return list(dict.fromkeys(os.path.abspath(p) for p in result))


def prepare_audio(data, samplerate, rate=DEFAULT_RATE, normalize=False,
                  loop=False, loop_start_ms=0.0, crossfade_ms=0.0):
    """
    Turn raw audio into PSX-ready mono float32 at `rate`.
    Returns (samples, loop_start_sample). In loop mode both the loop start and
    the loop length are aligned to 28-sample SPU blocks, so the loop is seamless on hardware.
    """
    data = np.asarray(data, dtype=np.float32)
    if data.ndim > 1:
        data = data.mean(axis=1, dtype=np.float32)
    if data.size == 0:
        raise ForgeError("File contains no audio.")

    if samplerate != rate:
        # soxr VHQ: proper band-limited resampling, no FFT edge ringing like scipy.signal.resample
        data = soxr.resample(data, samplerate, rate, quality="VHQ").astype(np.float32, copy=False)

    if normalize:
        peak = float(np.max(np.abs(data)))
        if peak > 0:
            data = data * np.float32(0.966 / peak)  # -0.3 dBFS

    loop_start = 0
    if loop:
        # Snap loop start down to a block boundary
        loop_start = int(round(loop_start_ms * rate / 1000.0))
        loop_start -= loop_start % SPU_BLOCK_SAMPLES
        if loop_start >= len(data) - SPU_BLOCK_SAMPLES:
            raise ForgeError("Loop start is past the end of the sample.")

        # Trim the end so the loop length is a multiple of 28
        excess = (len(data) - loop_start) % SPU_BLOCK_SAMPLES
        if excess:
            data = data[:-excess]

        fade = int(round(crossfade_ms * rate / 1000.0))
        if fade > 0:
            data, loop_start = _crossfade_loop(data, loop_start, fade)

    return np.clip(data, -1.0, 1.0), loop_start


def _crossfade_loop(data, loop_start, fade):
    """
    Equal-power crossfade of the loop tail into the audio right before the loop start,
    so jumping from the end back to the start is click-free. Keeps block alignment.
    """
    loop_len = len(data) - loop_start
    if loop_start > 0:
        fade = min(fade, loop_start, loop_len // 2)
        pre = data[loop_start - fade:loop_start]
    else:
        # Nothing before the start: sacrifice the head (rounded to whole blocks)
        fade = min(fade, loop_len // 2)
        fade -= fade % SPU_BLOCK_SAMPLES
        pre = data[:fade]
        data = data[fade:]
    if fade <= 0:
        return data, loop_start

    t = np.linspace(0.0, np.pi / 2, fade, dtype=np.float32)
    data = data.copy()
    data[-fade:] = data[-fade:] * np.cos(t) + pre * np.sin(t)
    return data, loop_start


def encode_vag(samples, rate, out_path, encoder, loop=False, loop_start=0, name=""):
    """Encode prepared mono samples to a .vag file with psxavenc."""
    if not encoder:
        raise ForgeError("psxavenc not found. Put it into the bin/ folder or on PATH.")

    fd, temp_wav = tempfile.mkstemp(prefix="psxforge_", suffix=".wav")
    os.close(fd)
    try:
        sf.write(temp_wav, samples, rate, subtype="PCM_16")

        # -a 16: pad only to one ADPCM block instead of 64 bytes
        cmd = [encoder, "-q", "-t", "vag", "-f", str(rate), "-a", str(SPU_BLOCK_BYTES)]
        if loop:
            # Only the loop-end flag; the loop-start flag is patched below with block precision
            cmd.append("-L")
        cmd += [temp_wav, out_path]

        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
        if proc.returncode != 0:
            raise ForgeError(f"psxavenc failed:\n{(proc.stderr or proc.stdout).strip()}")
    finally:
        try:
            os.remove(temp_wav)
        except OSError:
            pass

    _patch_vag(out_path, loop, loop_start, name)


def _patch_vag(path, loop, loop_start, name):
    """Set the loop-start flag on the right block and store the sample name in the header."""
    with open(path, "r+b") as f:
        vag = bytearray(f.read())
        if vag[:4] != b"VAGp":
            raise ForgeError("psxavenc produced an invalid .vag file.")
        # Header name: 16 bytes ASCII at offset 32
        vag[32:48] = name.encode("ascii", "replace")[:16].ljust(16, b"\0")
        if loop:
            # +1: psxavenc prepends a silent block to reset the decoder
            block = 1 + loop_start // SPU_BLOCK_SAMPLES
            offset = VAG_HEADER_SIZE + block * SPU_BLOCK_BYTES + 1
            if offset >= len(vag):
                raise ForgeError("Loop start is outside of the encoded data.")
            vag[offset] |= FLAG_START | FLAG_REPEAT
        f.seek(0)
        f.write(vag)


def decode_vag(path):
    """
    Decode a mono .vag into int16 samples, exactly like the SPU does (minus pitch interpolation).
    Returns (samples, rate, loop_start or None).
    """
    with open(path, "rb") as f:
        vag = f.read()
    if vag[:4] != b"VAGp" or len(vag) < VAG_HEADER_SIZE:
        raise ForgeError(f"Not a VAG file: {path}")
    size, rate = struct.unpack(">II", vag[12:20])
    body = np.frombuffer(vag, dtype=np.uint8, offset=VAG_HEADER_SIZE)
    blocks = body[:(min(size, body.size) // SPU_BLOCK_BYTES) * SPU_BLOCK_BYTES].reshape(-1, SPU_BLOCK_BYTES)

    # Unpack nibbles (low first) to signed 4-bit, then apply per-block shift: (n << 12) >> shift
    raw = blocks[:, 2:]
    nibbles = np.empty((len(blocks), SPU_BLOCK_SAMPLES), dtype=np.int32)
    nibbles[:, 0::2] = raw & 0x0F
    nibbles[:, 1::2] = raw >> 4
    nibbles = np.where(nibbles >= 8, nibbles - 16, nibbles) << 12
    shift = (blocks[:, 0] & 0x0F).astype(np.int32)
    shift[shift > 12] = 9  # SPU quirk for invalid shift values
    nibbles >>= shift[:, None]
    filters = np.minimum(blocks[:, 0] >> 4, 4).tolist()
    flags = blocks[:, 1]

    # The prediction filter is recursive, so this part stays a plain loop
    out = np.empty(nibbles.size, dtype=np.int16)
    coded = nibbles.tolist()
    s1 = s2 = 0
    i = 0
    for b, filt in enumerate(filters):
        k0, k1 = _FILTER_POS[filt], _FILTER_NEG[filt]
        for v in coded[b]:
            s = v + ((s1 * k0 + s2 * k1 + 32) >> 6)
            s = 32767 if s > 32767 else -32768 if s < -32768 else s
            out[i] = s
            s2, s1 = s1, s
            i += 1

    loop_start = None
    starts = np.nonzero(flags & FLAG_START)[0]
    ends = np.nonzero(flags & FLAG_END)[0]
    if starts.size and ends.size and flags[ends[0]] & FLAG_REPEAT:
        loop_start = int(starts[0]) * SPU_BLOCK_SAMPLES
        out = out[:(int(ends[0]) + 1) * SPU_BLOCK_SAMPLES]
    return out, rate, loop_start


def write_wav(path, samples, rate):
    """Write int16 mono samples with the stdlib wave module."""
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.astype("<i2").tobytes())


def render_preview(samples, loop_start, rate, seconds=8.0):
    """Intro + repeated loop, so a preview sounds like the sample held on hardware."""
    if loop_start is None:
        return samples
    loop = samples[loop_start:]
    if loop.size == 0:
        return samples
    repeats = max(1, int(np.ceil((seconds * rate - loop_start) / loop.size)))
    return np.concatenate([samples[:loop_start]] + [loop] * repeats)


def output_paths(input_path, out_dir=None):
    """Return (vag_path, psx_wav_path) for an input file."""
    base = os.path.splitext(os.path.basename(input_path))[0]
    folder = os.path.normpath(out_dir or os.path.dirname(input_path))
    return os.path.join(folder, base + ".vag"), os.path.join(folder, base + ".psx.wav")


def convert_file(input_path, encoder, rate=DEFAULT_RATE, normalize=False, loop=False,
                 loop_start_ms=0.0, crossfade_ms=0.0, export_wav=False, out_dir=None):
    """Full pipeline for one file. Returns a dict with output info."""
    if not 1000 <= rate <= MAX_RATE:
        raise ForgeError(f"Sample rate must be between 1000 and {MAX_RATE} Hz.")
    try:
        data, samplerate = sf.read(input_path, dtype="float32", always_2d=True)
    except Exception as e:
        raise ForgeError(f"Can't read audio: {e}") from e

    samples, loop_start = prepare_audio(data, samplerate, rate, normalize, loop, loop_start_ms, crossfade_ms)

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    vag_path, wav_path = output_paths(input_path, out_dir)
    name = os.path.splitext(os.path.basename(input_path))[0]
    encode_vag(samples, rate, vag_path, encoder, loop, loop_start, name)

    if export_wav:
        decoded, _, _ = decode_vag(vag_path)
        # Drop psxavenc's leading silent block
        write_wav(wav_path, decoded[SPU_BLOCK_SAMPLES:], rate)

    return {
        "vag": vag_path,
        "wav": wav_path if export_wav else None,
        "samples": len(samples),
        "loop_start": loop_start if loop else None,
        "bytes": os.path.getsize(vag_path),
    }
