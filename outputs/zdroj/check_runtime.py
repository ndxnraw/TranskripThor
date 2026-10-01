"""Fail closed: never label a legacy-only executable as the complete 1.5 release."""
def check():
    import torch
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
    import faster_whisper
    print('Local model runtimes available; CUDA:', torch.cuda.is_available())

if __name__ == '__main__':
    check()
