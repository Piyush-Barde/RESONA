# backend/pipelines/preprocess.py
import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import librosa
import numpy as np
import soundfile as sf

# ==============================================================================
# 🚀 PATH ANCHORING (Guarantees script finds data folders from anywhere)
# ==============================================================================
# Finds the 'backend' folder by looking one level up from this script
pipeline_dir = Path(__file__).resolve().parent
backend_root = pipeline_dir.parent

if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

# Remove Anaconda pollution if present
sys.path = [path for path in sys.path if not ("anaconda3" in path.lower() and "site-packages" in path.lower())]

# ==============================================================================
# CORE DSP PIPELINE
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("ResonaDataPipeline")

class AudioPreprocessor:
    def __init__(self, target_sr: int = 16000, target_dbfs: float = -20.0, top_db_trim: int = 25):
        self.target_sr = target_sr
        self.target_dbfs = target_dbfs
        self.top_db_trim = top_db_trim

    def normalize_loudness(self, audio_signal: np.ndarray) -> np.ndarray:
        rms = np.sqrt(np.mean(np.square(audio_signal)))
        if rms == 0:
            return audio_signal
        target_linear = 10 ** (self.target_dbfs / 20.0)
        gain = target_linear / rms
        normalized = audio_signal * gain
        max_peak = np.max(np.abs(normalized))
        if max_peak > 1.0:
            normalized = normalized / max_peak
        return normalized

    def process_file(self, input_path: Path, output_path: Path) -> Optional[float]:
        try:
            signal, sr = librosa.load(str(input_path), sr=self.target_sr, mono=True)
            if len(signal) == 0:
                logger.warning(f"Skipping empty audio track: {input_path.name}")
                return None

            trimmed_signal, _ = librosa.effects.trim(signal, top_db=self.top_db_trim)
            processed_signal = self.normalize_loudness(trimmed_signal)

            sf.write(str(output_path), processed_signal, self.target_sr, format='WAV', subtype='PCM_16')
            return float(len(processed_signal) / self.target_sr)
        except Exception as e:
            logger.error(f"DSP Pipeline failed on file {input_path.name}: {str(e)}")
            return None

class DatasetGenerator:
    def __init__(self, preprocessor: AudioPreprocessor):
        self.preprocessor = preprocessor

    def run(self, raw_dir_path: Path, processed_dir_path: Path, manifest_name: str = "train_manifest.jsonl"):
        processed_dir_path.mkdir(parents=True, exist_ok=True)
        manifest_path = processed_dir_path / manifest_name
        manifest_entries: List[Dict[str, Any]] = []
        audio_extensions = {".wav", ".mp3", ".m4a", ".flac"}
        
        logger.info(f"🚀 Initializing Resona Dataset Compiler (Routed in /pipelines)...")
        logger.info(f"Target Input Directory: {raw_dir_path.resolve()}")

        if not raw_dir_path.exists():
            logger.error(f"Input directory does not exist! Checked: {raw_dir_path.resolve()}")
            return

        for file_path in raw_dir_path.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in audio_extensions:
                base_name = file_path.stem
                transcript_path = raw_dir_path / f"{base_name}.txt"

                if not transcript_path.exists():
                    logger.warning(f"Data integrity issue: Missing transcript label for {file_path.name}. Skipping.")
                    continue

                output_audio_path = processed_dir_path / f"{base_name}_clean.wav"
                duration = self.preprocessor.process_file(file_path, output_audio_path)
                
                if duration is not None:
                    with open(transcript_path, "r", encoding="utf-8") as f:
                        transcript_text = f.read().strip()

                    manifest_entries.append({
                        "audio_filepath": str(output_audio_path.resolve()),
                        "text": transcript_text,
                        "duration_seconds": round(duration, 3)
                    })
                    logger.info(f"Successfully compiled entry: {base_name} [{round(duration, 2)}s]")

        with open(manifest_path, "w", encoding="utf-8") as f:
            for entry in manifest_entries:
                f.write(json.dumps(entry) + "\n")

        logger.info("=======================================================")
        logger.info(f"🎉 Preprocessing complete! Compiled {len(manifest_entries)} clean records.")
        logger.info(f"Manifest saved to ➔ {manifest_path.resolve()}")
        logger.info("=======================================================")

if __name__ == "__main__":
    # Define paths explicitly using our backend root anchor
    RAW_DATA_DIR = backend_root / "data" / "raw"
    PROCESSED_DATA_DIR = backend_root / "data" / "processed"

    preprocessor = AudioPreprocessor(target_sr=16000, target_dbfs=-20.0, top_db_trim=25)
    pipeline = DatasetGenerator(preprocessor)
    pipeline.run(raw_dir_path=RAW_DATA_DIR, processed_dir_path=PROCESSED_DATA_DIR)