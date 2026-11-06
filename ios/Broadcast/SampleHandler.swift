import CoreMedia
import ReplayKit

/// "iPhone audio" source: while a screen broadcast to this extension is running, iOS hands
/// it the audio of all apps (YouTube, Safari, podcasts, …). It is converted to 16 kHz mono
/// and written to the shared ring buffer; the app does the speech recognition (extensions
/// only get ~50 MB of memory, far too little for a speech model).
class SampleHandler: RPBroadcastSampleHandler {
    private var ring: SharedAudioRing?
    private var resampler: Resampler?

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        if let url = SharedAudioRing.fileURL() {
            ring = SharedAudioRing(url: url)
        }
        if ring == nil {
            let error = NSError(domain: "SwissRuDe", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "Swiss RU-DE: the shared App Group is missing. Reinstall the app with Xcode (see README).",
            ])
            finishBroadcastWithError(error)
        }
    }

    override func broadcastFinished() {
        ring = nil
    }

    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer, with sampleBufferType: RPSampleBufferType) {
        guard sampleBufferType == .audioApp, let ring else { return }
        guard let result = Self.monoSamples(sampleBuffer), !result.0.isEmpty else { return }
        let rate = result.1
        if resampler == nil || resampler!.inRate != rate {
            resampler = Resampler(inRate: rate, outRate: Double(SharedAudioRing.sampleRate))
        }
        ring.write(resampler!.process(result.0))
    }

    /// Reads any linear PCM layout ReplayKit delivers (16/32-bit int or float, big- or
    /// little-endian, interleaved or not) and mixes it down to mono floats.
    static func monoSamples(_ sb: CMSampleBuffer) -> ([Float], Double)? {
        guard let format = CMSampleBufferGetFormatDescription(sb),
              let asbdPointer = CMAudioFormatDescriptionGetStreamBasicDescription(format),
              let block = CMSampleBufferGetDataBuffer(sb)
        else { return nil }
        let asbd = asbdPointer.pointee
        guard asbd.mFormatID == kAudioFormatLinearPCM, asbd.mSampleRate > 0 else { return nil }

        let length = CMBlockBufferGetDataLength(block)
        guard length > 0 else { return nil }
        var data = [UInt8](repeating: 0, count: length)
        let status = data.withUnsafeMutableBytes { buffer in
            CMBlockBufferCopyDataBytes(block, atOffset: 0, dataLength: length, destination: buffer.baseAddress!)
        }
        guard status == kCMBlockBufferNoErr else { return nil }

        let flags = asbd.mFormatFlags
        let isFloat = flags & kAudioFormatFlagIsFloat != 0
        let bigEndian = flags & kAudioFormatFlagIsBigEndian != 0
        let nonInterleaved = flags & kAudioFormatFlagIsNonInterleaved != 0
        let bytes = Int(asbd.mBitsPerChannel) / 8
        guard bytes == 2 || bytes == 4 else { return nil }
        // Non-interleaved: the first channel's samples come first - use only that channel.
        let channels = nonInterleaved ? 1 : max(1, Int(asbd.mChannelsPerFrame))
        let frames = min(CMSampleBufferGetNumSamples(sb), length / (bytes * channels))
        guard frames > 0 else { return nil }

        var out = [Float](repeating: 0, count: frames)
        data.withUnsafeBytes { raw in
            func sample(_ index: Int) -> Float {
                let offset = index * bytes
                if bytes == 2 {
                    let v = raw.loadUnaligned(fromByteOffset: offset, as: UInt16.self)
                    let host = bigEndian ? UInt16(bigEndian: v) : UInt16(littleEndian: v)
                    return Float(Int16(bitPattern: host)) / 32_768
                }
                let v = raw.loadUnaligned(fromByteOffset: offset, as: UInt32.self)
                let host = bigEndian ? UInt32(bigEndian: v) : UInt32(littleEndian: v)
                return isFloat ? Float(bitPattern: host) : Float(Int32(bitPattern: host)) / 2_147_483_648
            }
            for f in 0..<frames {
                var sum: Float = 0
                for c in 0..<channels {
                    sum += sample(f * channels + c)
                }
                out[f] = sum / Float(channels)
            }
        }
        return (out, asbd.mSampleRate)
    }
}
