"use strict";
/* Jitter-tolerant 48 kHz stereo PCM stream from VICE Libretro.
 *
 * The 20ms SID samples are continuous audio; they are not independent
 * "sound effects". Schedule all received chunks on a stable Web Audio
 * timeline, with a small WAN jitter buffer and gentle clock-drift
 * compensation. Never rewind an already scheduled timeline.
 */
(function () {
  const TARGET_LEAD = 0.22;
  const START_LEAD = 0.23;
  const MIN_LEAD = 0.012;
  const MAX_RATE_CHANGE = 0.025;
  const clamp = (x, min, max) => Math.max(min, Math.min(max, x));

  window.createC64Audio = function createC64Audio(AudioContextFactory) {
    let context = null;
    let nextAt = 0;
    let muted = false;
    let underflows = 0;
    let received = 0;
    let played = 0;
    let skipped = 0;
    let lastLead = 0;

    async function enable() {
      if (!context) context = new AudioContextFactory({latencyHint: "playback"});
      if (context.state !== "running") await context.resume();
      if (nextAt < context.currentTime) nextAt = context.currentTime + START_LEAD;
    }

    function receive(bytes, sampleRate) {
      received++;
      if (muted || !context || context.state !== "running") {
        skipped++;
        return;
      }
      if (!Number.isFinite(sampleRate) || sampleRate < 8000 || sampleRate > 192000 ||
          bytes.byteLength < 4 || bytes.byteLength % 4 !== 0) {
        skipped++;
        return;
      }
      const now = context.currentTime;
      if (nextAt < now + MIN_LEAD) {
        if (nextAt !== 0) underflows++;
        nextAt = now + START_LEAD;
      }
      const count = bytes.byteLength / 4;
      const samples = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
      const buffer = context.createBuffer(2, count, sampleRate);
      const left = buffer.getChannelData(0), right = buffer.getChannelData(1);
      for (let i = 0; i < count; i++) {
        left[i] = samples.getInt16(i * 4, true) / 32768;
        right[i] = samples.getInt16(i * 4 + 2, true) / 32768;
      }
      const source = context.createBufferSource();
      source.buffer = buffer;
      // Compensate gently for small sample-clock / emulated FPS differences.
      // No timeline seek/restart, which previously skipped parts of the tune.
      const lead = nextAt - now;
      const playbackRate = clamp(
        1 + (lead - TARGET_LEAD) * 0.075,
        1 - MAX_RATE_CHANGE,
        1 + MAX_RATE_CHANGE
      );
      source.playbackRate.value = playbackRate;
      source.connect(context.destination);
      source.start(nextAt);
      nextAt += (count / sampleRate) / playbackRate;
      lastLead = nextAt - now;
      played++;
    }

    function setMuted(value) {
      muted = Boolean(value);
      if (!muted && context) nextAt = context.currentTime + START_LEAD;
    }

    function reset() {
      // A new room or disconnected session gets a fresh audio timeline.
      // Old queued nodes will finish naturally; none can leak into a later
      // room because reset is only used after navigating/replacing session.
      nextAt = 0;
      underflows = received = played = skipped = 0;
      lastLead = 0;
    }

    function stats() {
      return {
        leadMs: Math.max(0, Math.round(lastLead * 1000)),
        underflows, received, played, skipped,
        state: context ? context.state : "not-enabled"
      };
    }
    return {enable, receive, setMuted, reset, stats};
  };
}());
