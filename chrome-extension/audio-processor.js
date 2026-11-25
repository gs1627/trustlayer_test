/**
 * TRUSTLAYER Guardian — PCM16 AudioWorklet Processor
 *
 * Runs in the Audio Worklet thread (not the main thread).
 *
 * Receives Float32 samples from the WebAudio graph (already resampled to
 * 16 kHz by the AudioContext), downmixes to mono if necessary, then
 * converts to signed 16-bit little-endian PCM and posts the ArrayBuffer
 * back to the offscreen document via port.postMessage.
 *
 * Frame size: 128 samples (the fixed WebAudio render quantum) ≈ 8 ms per frame.
 * We accumulate frames to send ~100 ms chunks (1600 samples at 16 kHz).
 */

class PCM16Processor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffers = [];
    this._samplesAccumulated = 0;
    // Send every 100 ms worth of audio at 16 kHz → 1600 samples → 3200 bytes
    this._targetSamples = 1600;
  }

  /**
   * Convert a Float32Array of mono samples to an Int16 ArrayBuffer (PCM16LE).
   */
  static float32ToPCM16LE(float32) {
    const length = float32.length;
    const buffer = new ArrayBuffer(length * 2);
    const view = new DataView(buffer);
    for (let i = 0; i < length; i++) {
      // Clamp to [-1, 1] then scale
      let s = float32[i];
      if (s > 1) s = 1;
      else if (s < -1) s = -1;
      // Scale to Int16 range
      const intSample = s < 0 ? s * 0x8000 : s * 0x7FFF;
      view.setInt16(i * 2, Math.round(intSample), true /* little-endian */);
    }
    return buffer;
  }

  /**
   * Downmix multi-channel audio to mono by averaging all channels.
   */
  static downmixToMono(inputs) {
    const channelData = inputs[0]; // first input
    if (!channelData || channelData.length === 0) return null;

    if (channelData.length === 1) {
      // Already mono — copy to avoid modifying the shared buffer
      return Float32Array.from(channelData[0]);
    }

    const numChannels = channelData.length;
    const numSamples = channelData[0].length;
    const mono = new Float32Array(numSamples);
    for (let i = 0; i < numSamples; i++) {
      let sum = 0;
      for (let ch = 0; ch < numChannels; ch++) {
        sum += channelData[ch][i];
      }
      mono[i] = sum / numChannels;
    }
    return mono;
  }

  process(inputs, _outputs, _parameters) {
    const mono = PCM16Processor.downmixToMono(inputs);
    if (!mono || mono.length === 0) return true;

    this._buffers.push(mono);
    this._samplesAccumulated += mono.length;

    if (this._samplesAccumulated >= this._targetSamples) {
      // Concatenate accumulated buffers
      const total = new Float32Array(this._samplesAccumulated);
      let offset = 0;
      for (const buf of this._buffers) {
        total.set(buf, offset);
        offset += buf.length;
      }
      this._buffers = [];
      this._samplesAccumulated = 0;

      // Convert to PCM16LE and transfer (zero-copy) to main thread
      const pcm16 = PCM16Processor.float32ToPCM16LE(total);
      this.port.postMessage(pcm16, [pcm16]);
    }

    return true; // keep the processor alive
  }
}

registerProcessor('pcm16-processor', PCM16Processor);
