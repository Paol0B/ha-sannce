import io
import math
import struct
import wave


def read_wav(data: bytes) -> tuple[int, list[int]]:
    with wave.open(io.BytesIO(data)) as wav:
        if (wav.getnchannels(), wav.getsampwidth()) != (1, 2):
            raise ValueError("expected mono 16-bit audio")
        frames = wav.readframes(wav.getnframes())
        samples = [sample for (sample,) in struct.iter_unpack("<h", frames)]
        return wav.getframerate(), samples


def wav_seconds(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as wav:
        return wav.getnframes() / wav.getframerate()


def tone_wav(frequency: float, seconds: float, rate: int = 8000) -> bytes:
    count = round(seconds * rate)
    samples = [
        round(16000 * math.sin(2 * math.pi * frequency * n / rate))
        for n in range(count)
    ]
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(struct.pack(f"<{count}h", *samples))
    return output.getvalue()


def power(samples: list[int], rate: int, frequency: float) -> float:
    # Goertzel: the DFT power at one frequency
    coefficient = 2 * math.cos(2 * math.pi * frequency / rate)
    previous = before = 0.0
    for sample in samples:
        previous, before = sample + coefficient * previous - before, previous
    return previous * previous + before * before - coefficient * previous * before


def peak_frequency(
    samples: list[int], rate: int, low: int, high: int, step: int
) -> int:
    return max(range(low, high + 1, step), key=lambda freq: power(samples, rate, freq))


def rms(samples: list[int]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))
