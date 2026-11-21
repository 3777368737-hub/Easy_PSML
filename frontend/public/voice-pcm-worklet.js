class VoicePcmWorklet extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.frameSamples = options.processorOptions?.frameSamples || 1600;
    this.buffer = new Float32Array(this.frameSamples);
    this.offset = 0;
    this.active = false;
    this.port.onmessage = (event) => {
      if (event.data?.type === "active") {
        this.active = Boolean(event.data.value);
        if (!this.active) {
          this.offset = 0;
        }
      }
    };
  }

  process(inputs) {
    if (!this.active) return true;
    const channels = inputs[0] || [];
    if (!channels.length) return true;

    const frameLength = channels[0].length;
    for (let index = 0; index < frameLength; index += 1) {
      let sample = 0;
      for (const channel of channels) {
        sample += channel[index] || 0;
      }
      sample /= channels.length;
      this.buffer[this.offset] = Math.max(-1, Math.min(1, sample));
      this.offset += 1;
      if (this.offset === this.frameSamples) {
        const pcm = new Int16Array(this.frameSamples);
        for (let pcmIndex = 0; pcmIndex < this.frameSamples; pcmIndex += 1) {
          const value = this.buffer[pcmIndex];
          pcm[pcmIndex] = value < 0 ? value * 0x8000 : value * 0x7fff;
        }
        this.port.postMessage(pcm.buffer, [pcm.buffer]);
        this.offset = 0;
      }
    }
    return true;
  }
}

registerProcessor("gradpilot-pcm-worklet", VoicePcmWorklet);
