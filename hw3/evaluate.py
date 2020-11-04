from collections import defaultdict

import numpy as np
import torch as th
import torch.nn.functional as F
from torch.utils.data import DataLoader
from mir_eval.util import midi_to_hz
from mir_eval.transcription import precision_recall_f1_overlap as evaluate_notes

from dataset import MAESTRO_small
from constants import HOP_SIZE, SAMPLE_RATE, MIN_MIDI


from mir_eval.util import midi_to_hz

def evaluate(model, device):
    dataset = MAESTRO_small(groups=['test'], sequence_length=16000*30, hop_size=HOP_SIZE, random_sample=False)
    metrics = defaultdict(list)
    with th.no_grad():
        loader = DataLoader(dataset, batch_size=1, shuffle=False)
        for batch in loader:
            frame_logit, onset_logit = model(batch['audio'].to(device))
            frame_pred = F.sigmoid(frame_logit[0])
            onset_pred = F.sigmoid(onset_logit[0])

            p_est, i_est = extract_notes(onset_pred, frame_pred)
            p_ref, i_ref = extract_notes(batch['onset'][0], batch['frame'][0])

            scaling = HOP_SIZE / SAMPLE_RATE

            i_ref = (i_ref * scaling).reshape(-1, 2)
            p_ref = np.array([midi_to_hz(MIN_MIDI + pitch) for pitch in p_ref])
            i_est = (i_est * scaling).reshape(-1, 2)
            p_est = np.array([midi_to_hz(MIN_MIDI + pitch) for pitch in p_est])

            p, r, f, o = evaluate_notes(
                i_ref, p_ref, i_est, p_est, offset_ratio=None)
            metrics['metric/note/precision'].append(p)
            metrics['metric/note/recall'].append(r)
            metrics['metric/note/f1'].append(f)
            metrics['metric/note/overlap'].append(o)

            p, r, f, o = evaluate_notes(i_ref, p_ref, i_est, p_est)
            metrics['metric/note-with-offsets/precision'].append(p)
            metrics['metric/note-with-offsets/recall'].append(r)
            metrics['metric/note-with-offsets/f1'].append(f)
            metrics['metric/note-with-offsets/overlap'].append(o)

    return metrics


def extract_notes(onsets, frames, onset_threshold=0.5, frame_threshold=0.5):
    """
    Finds the note timings based on the onsets and frames information

    Parameters
    ----------
    onsets: torch.FloatTensor, shape = [frames, bins]
    frames: torch.FloatTensor, shape = [frames, bins]
    onset_threshold: float
    frame_threshold: float

    Returns
    -------
    pitches: np.ndarray of bin_indices
    intervals: np.ndarray of rows containing (onset_index, offset_index)
    """
    onsets = (onsets > onset_threshold).type(th.int).cpu()
    frames = (frames > frame_threshold).type(th.int).cpu()
    onset_diff = th.cat(
        [onsets[:1, :], onsets[1:, :] - onsets[:-1, :]], dim=0) == 1

    pitches = []
    intervals = []

    for nonzero in onset_diff.nonzero():
        frame = nonzero[0].item()
        pitch = nonzero[1].item()

        onset = frame
        offset = frame

        while onsets[offset, pitch].item() or frames[offset, pitch].item():
            offset += 1
            if offset == onsets.shape[0]:
                break
            if (offset != onset) and onsets[offset, pitch].item():
                break

        if offset > onset:
            pitches.append(pitch)
            intervals.append([onset, offset])

    return np.array(pitches), np.array(intervals)