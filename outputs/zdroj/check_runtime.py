"""Overenie závislostí Windows zostavy. Voliteľné hlasy neblokujú bežný prepis."""
def check():
    import torch
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
    import faster_whisper
    import sounddevice
    import tkinterdnd2
    print('Local model runtimes available; CUDA:', torch.cuda.is_available())

if __name__ == '__main__':
    check()
