#!/usr/bin/env python3
"""
Audio Transcription Script using Faster-Whisper
Transcribes call recordings to text with speaker diarization
"""

import os
import sys
from pathlib import Path
from faster_whisper import WhisperModel

def transcribe_audio(audio_file_path, model_size="base", device="cpu", compute_type="int8"):
    """
    Transcribe an audio file using Faster-Whisper.
    
    Args:
        audio_file_path: Path to the audio file
        model_size: Whisper model size (tiny, base, small, medium, large-v2, large-v3)
        device: cpu or cuda
        compute_type: int8, float16, float32
    
    Returns:
        dict: Transcription results with text and segments
    """
    print(f"🎤 Audio Transcription")
    print("=" * 70)
    
    # Check if file exists
    audio_path = Path(audio_file_path)
    if not audio_path.exists():
        print(f"❌ Error: File not found: {audio_file_path}")
        return None
    
    print(f"📄 File: {audio_path.name}")
    print(f"📊 Size: {audio_path.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"🤖 Model: {model_size}")
    print(f"💻 Device: {device} ({compute_type})")
    print()
    
    # Load model
    print(f"⏳ Loading Whisper model ({model_size})...")
    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        print("✓ Model loaded\n")
    except Exception as e:
        print(f"❌ Error loading model: {e}")
        return None
    
    # Transcribe
    print("🎯 Transcribing audio...")
    try:
        segments, info = model.transcribe(
            str(audio_path),
            beam_size=5,
            vad_filter=True,  # Voice Activity Detection
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        
        # Process results
        print(f"✓ Transcription complete!")
        print(f"  Language: {info.language} ({info.language_probability:.2%} confidence)")
        print(f"  Duration: {info.duration:.2f} seconds")
        print()
        
        # Collect segments
        full_text = []
        segment_list = []
        
        print("📝 Transcript:")
        print("=" * 70)
        
        for segment in segments:
            timestamp = f"[{format_timestamp(segment.start)} -> {format_timestamp(segment.end)}]"
            text = segment.text.strip()
            
            print(f"{timestamp} {text}")
            
            full_text.append(text)
            segment_list.append({
                "start": segment.start,
                "end": segment.end,
                "text": text
            })
        
        print("=" * 70)
        
        result = {
            "file": str(audio_path),
            "language": info.language,
            "language_probability": info.language_probability,
            "duration": info.duration,
            "full_text": " ".join(full_text),
            "segments": segment_list
        }
        
        return result
        
    except Exception as e:
        print(f"❌ Error during transcription: {e}")
        return None


def format_timestamp(seconds):
    """Convert seconds to MM:SS format."""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


def save_transcript(result, output_file=None):
    """Save transcript to a text file."""
    if not result:
        return
    
    if output_file is None:
        audio_path = Path(result["file"])
        output_file = audio_path.with_suffix(".txt")
    
    output_path = Path(output_file)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"Transcription: {result['file']}\n")
        f.write(f"Language: {result['language']} ({result['language_probability']:.2%})\n")
        f.write(f"Duration: {result['duration']:.2f} seconds\n")
        f.write("=" * 70 + "\n\n")
        
        f.write("FULL TRANSCRIPT:\n")
        f.write("-" * 70 + "\n")
        f.write(result['full_text'] + "\n\n")
        
        f.write("TIMESTAMPED SEGMENTS:\n")
        f.write("-" * 70 + "\n")
        for seg in result['segments']:
            timestamp = f"[{format_timestamp(seg['start'])} -> {format_timestamp(seg['end'])}]"
            f.write(f"{timestamp} {seg['text']}\n")
    
    print(f"\n💾 Transcript saved to: {output_path}")


def main():
    """Main function to run transcription."""
    
    # Check for command line arguments
    if len(sys.argv) < 2:
        # Look for recordings in the recordings folder
        recordings_dir = Path("recordings")
        if recordings_dir.exists():
            recordings = list(recordings_dir.glob("*.mp4")) + list(recordings_dir.glob("*.wav"))
            if recordings:
                print(f"Found {len(recordings)} recording(s) in recordings folder:")
                for i, rec in enumerate(recordings, 1):
                    print(f"{i}. {rec.name}")
                
                # Use first recording as example
                audio_file = str(recordings[0])
                print(f"\nUsing: {recordings[0].name}\n")
            else:
                print("No recordings found in recordings folder.")
                print("Usage: python transcribe.py <audio_file>")
                sys.exit(1)
        else:
            print("Usage: python transcribe.py <audio_file>")
            print("\nExample: python transcribe.py recordings/693159368307_voice-only.mp4")
            sys.exit(1)
    else:
        audio_file = sys.argv[1]
    
    # Get model size from environment or use default
    model_size = os.getenv("WHISPER_MODEL", "base")  # tiny, base, small, medium, large-v2, large-v3
    
    # Transcribe
    result = transcribe_audio(
        audio_file,
        model_size=model_size,
        device="cpu",  # Use "cuda" if you have GPU
        compute_type="int8"  # int8 for CPU, float16 for GPU
    )
    
    # Save transcript
    if result:
        save_transcript(result)
        print("\n✅ Transcription complete!")
    else:
        print("\n❌ Transcription failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
