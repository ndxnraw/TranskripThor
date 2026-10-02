"""Optional local voice clustering, independent of ASR language detection.

WeSpeaker ResNet34-LM weights: CC BY 4.0, WeSpeaker authors.
https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34-LM
No real-world identity inference; short turns/overlap require human review.
"""
from pathlib import Path


class VoiceEncoder:
    def __init__(self, folder):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(Path(folder)/'voxceleb_resnet34_LM.onnx'),
            sess_options=options, providers=['CPUExecutionProvider'])

    def embedding(self, audio):
        try:
            import kaldi_native_fbank as knf
        except ImportError as exc:
            raise RuntimeError('Chýba voliteľná súčasť rozlíšenia hlasov. Nainštalujte requirements-speakers.txt alebo použite plnú Windows zostavu. Bežný prepis zostáva dostupný.') from exc
        import numpy as np
        options = knf.FbankOptions()
        options.frame_opts.dither = 0
        options.frame_opts.samp_freq = 16000
        options.frame_opts.frame_length_ms = 25
        options.frame_opts.frame_shift_ms = 10
        options.frame_opts.window_type = 'hamming'
        options.mel_opts.num_bins = 80
        options.mel_opts.debug_mel = False
        options.use_energy = False
        bank = knf.OnlineFbank(options)
        bank.accept_waveform(16000, (audio * 32768).tolist())
        bank.input_finished()
        if bank.num_frames_ready < 10:
            return None
        features = np.stack([bank.get_frame(i) for i in range(bank.num_frames_ready)])
        features = (features - features.mean(axis=0, keepdims=True)).astype('float32')[None]
        vector = self.session.run(None, {self.session.get_inputs()[0].name: features})[0].reshape(-1)
        norm = np.linalg.norm(vector)
        return vector / norm if norm > 0 and np.isfinite(norm) else None


def cluster(embeddings, threshold=0.65):
    """Bounded-memory online cosine clustering; labels follow first occurrence."""
    import numpy as np
    centers, counts, labels = [], [], []
    for vector in embeddings:
        if vector is None:
            labels.append('Neurčený hovoriaci')
            continue
        scores = [float(np.dot(vector, center)) for center in centers]
        best = int(np.argmax(scores)) if scores else -1
        if best < 0 or scores[best] < threshold:
            best = len(centers)
            centers.append(vector.copy())
            counts.append(1)
        else:
            merged = centers[best] * counts[best] + vector
            centers[best] = merged / max(1e-12, np.linalg.norm(merged))
            counts[best] += 1
        labels.append(f'Hovoriaci {best+1}')
    return labels


def assign_speakers(audio, segments, model_folder, stop, emit, threshold=0.65):
    import numpy as np
    encoder = VoiceEncoder(model_folder)
    embeddings = []
    for index, segment in enumerate(segments):
        if stop.is_set():
            raise InterruptedError('Rozlíšenie hlasov zastavené. Pôvodné priradenia zostávajú zachované.')
        start, end = round(segment['start']*16000), round(segment['end']*16000)
        if end-start < 16000:
            embeddings.append(None)
        else:
            # Multiple short windows bound feature memory for long ASR segments.
            vectors = []
            for begin in range(start, end, 3*16000):
                if stop.is_set():
                    raise InterruptedError('Rozlíšenie hlasov zastavené.')
                chunk = audio[begin:min(end,begin+3*16000)]
                if len(chunk) >= 16000:
                    vector = encoder.embedding(chunk)
                    if vector is not None:
                        vectors.append(vector)
            mean = np.mean(vectors,axis=0) if vectors else None
            embeddings.append(mean / max(1e-12,np.linalg.norm(mean)) if mean is not None else None)
        emit(f'Rozlišujem hlasy lokálne na CPU: {index+1}/{len(segments)} úsekov.')
    return cluster(embeddings, threshold)
