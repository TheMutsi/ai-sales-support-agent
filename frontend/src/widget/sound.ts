let context: AudioContext | null = null;

/**
 * A short "ping" made with Web Audio, so the single script needs no audio file.
 * Browsers only let a page make sound after the visitor has interacted with it; until then this
 * does nothing, and it never throws.
 */
export function playPing(): void {
  try {
    context ??= new AudioContext();
    void context.resume();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const now = context.currentTime;
    oscillator.frequency.value = 880;
    gain.gain.setValueAtTime(0.15, now);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.25);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(now);
    oscillator.stop(now + 0.25);
  } catch {
    /* no audio available: the badge still shows */
  }
}
