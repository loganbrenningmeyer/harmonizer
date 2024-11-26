import pygame
import torch
import torch.nn.functional as F
import numpy as np
import time

from utils.data.mappings import *
from utils.data.load_data import get_songs_notes

# -- Define constants for playback
SAMPLE_RATE = 44100
FADE_DURATION = 0.02
VOLUME = 0.25

NOTE_DURATION = 1
CHORD_DURATION = 4

# -- Active sounds list to ensure playback
active_sounds = []


def generate_sine_wave(frequency, duration, sample_rate=SAMPLE_RATE):
    """
    Generates a sine wave for a given frequency and duration with fade-in and fade-out.
    """
    # -- Create sine wave for given frequency, sample_rate, and duration
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    wave = np.sin(frequency * t * 2 * np.pi)
    
    # -- Apply linear fade-in/fade-out to avoid audio pops
    fade_length = int(sample_rate * FADE_DURATION)
    envelope = np.ones_like(wave)

    envelope[:fade_length] = np.linspace(0, 1, fade_length)
    envelope[-fade_length:] = np.linspace(1, 0, fade_length)
    
    wave *= envelope
    
    # -- Normalize to 16-bit range
    audio = wave * (32767 / np.max(np.abs(wave)))

    return audio.astype(np.int16)


def play_note(note, duration=NOTE_DURATION, volume=VOLUME):
    # -- Get note frequency
    note_freq = NOTE_FREQUENCIES[note]

    # -- Create sine wave w/ note frequency
    note_wave = generate_sine_wave(note_freq, duration).astype(np.float32)
    
    # -- Scale volume to avoid distortion
    note_wave *= (2 * volume / 2)

    # -- Clip to 16-bit range
    note_wave = np.clip(note_wave, -32767, 32767)

    # -- Convert to stereo as 16-bit int
    note_wave = np.column_stack((note_wave, note_wave)).astype(np.int16)

    # -- Play note on channel 1
    note_channel = pygame.mixer.Channel(1)
    note_sound = pygame.sndarray.make_sound(note_wave)
    note_channel.play(note_sound)

    # -- Append to active_sounds
    active_sounds.append(note_sound)

def play_chord(chord, duration=CHORD_DURATION, volume=VOLUME):
    # -- Get chord note frequencies
    chord_note_freqs = [NOTE_FREQUENCIES[note] for note in CHORD_NOTES[chord]]

    # -- Initialize base wave
    chord_wave = np.zeros(int(SAMPLE_RATE * duration), dtype=np.float32)

    # -- Add sine waves for each chord note frequency
    for note_freq in chord_note_freqs:
        note_wave = generate_sine_wave(note_freq, duration).astype(np.float32)
        # Scale volume to avoid distortion
        chord_wave += note_wave * (2 * volume / len(chord_note_freqs))

    # -- Clip to 16-bit range
    chord_wave = np.clip(chord_wave, -32767, 32767)

    # -- Convert to stereo as 16-bit int
    chord_wave = np.column_stack((chord_wave, chord_wave)).astype(np.int16)

    # -- Play chord on channel 0
    chord_channel = pygame.mixer.Channel(0)
    chord_sound = pygame.sndarray.make_sound(chord_wave)
    chord_channel.play(chord_sound)

    # -- Append to active_sounds
    active_sounds.append(chord_sound)


def play_comp(notes, chord):
    '''
    Plays notes over a backing chord
    '''
    play_chord(chord)

    if notes[0] is not None:
        for note in notes:
            play_note(note)
            time.sleep(NOTE_DURATION)
    else:
        time.sleep(NOTE_DURATION)


def play_song(model_path: str, song_idx: int):
    # -- Initialize Pygame mixer
    pygame.mixer.pre_init(frequency=SAMPLE_RATE, size=-16, channels=2, buffer=512)
    pygame.mixer.init()

    # -- Set device
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    # -- Load HNN model in eval mode
    hnn = torch.load(model_path, map_location=device)
    hnn.eval()

    # -- Get note encodings of specified song_idx
    song_notes = get_songs_notes()[song_idx]

    # -- Initialize note/chord one-hot encoding arrays to index from
    note_enc_array = torch.eye(12, dtype=int)

    # -- Initialize state units
    state_units = torch.zeros((1, hnn.output_size)).to(device)

    for timestep in range(len(song_notes)):
        # Get one-hot encoded melody input
        note = song_notes[timestep]
        note_idx = NOTE_ENC_TO_IDX_REF.get(note[:2])

        if note_idx is not None:
            input_t = note_enc_array[note_idx].unsqueeze(0)
        else:
            input_t = torch.zeros((1, 12), dtype=int)

        # Determine meter units
        meter_units = F.one_hot(torch.arange(2, dtype=torch.long))[timestep % 2].to(device)     # [1, 0] on 1st beat, [0, 1] on 3rd beat
        meter_units = meter_units.expand((1, 2))

        # Concatenate state_units, melody inputs, and meter_units
        inputs = torch.cat([state_units, input_t, meter_units], dim=1)
        
        # Forward pass
        output = hnn(inputs)

        # Update state units
        state_units = F.softmax(output, dim=1) + hnn.state_units_decay * state_units
        state_units = state_units / state_units.sum(dim=1, keepdim=True)

        # Get note/chord as string for playback
        if NOTE_ENC_TO_NOTE_STR_REF.get(note[:2]) is not None:
            note_str = NOTE_ENC_TO_NOTE_STR_REF.get(note[:2]) + note[2]
        else:
            note_str = None

        chord_idx = int(np.argmax(output.detach().squeeze(0)))
        chord_str = IDX_TO_CHORD_STR_REF.get(chord_idx)

        # Playback note/chord
        print(f"note: {note_str}, chord: {chord_str}")
        play_comp([note_str], chord_str)


def main():
    play_song(model_path='../../saved_models/hnn/hidden1_64_melody_10/epoch100.pth', 
              song_idx=0)
    

if __name__ == "__main__":
    main()