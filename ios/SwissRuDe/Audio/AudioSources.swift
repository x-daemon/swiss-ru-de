import AVFoundation
import CoreMedia

enum AudioError: LocalizedError {
    case microphoneDenied
    case noInput
    case noAppGroup
    case noAudioTrack

    var errorDescription: String? {
        switch self {
        case .microphoneDenied: "Microphone access is off. Allow it in Settings → Privacy → Microphone."
        case .noInput: "No microphone available."
        case .noAppGroup: "iPhone audio needs the App Group - install the app with Xcode (see README)."
        case .noAudioTrack: "This file has no audio track."
        }
    }
}

enum AudioSessionMode {
    case record // microphone
    case playback // iPhone audio via broadcast; keeps the app running in the background
}

enum AudioSessionManager {
    static func activate(_ mode: AudioSessionMode) throws {
        let session = AVAudioSession.sharedInstance()
        switch mode {
        case .record:
            try session.setCategory(.playAndRecord, mode: .default, options: [.mixWithOthers, .defaultToSpeaker])
        case .playback:
            try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])
        }
        try session.setActive(true)
    }
}

/// Microphone → 16 kHz mono floats.
final class MicrophoneSource {
    private let engine = AVAudioEngine()

    func start(onSamples: @escaping ([Float]) -> Void) throws {
        try AudioSessionManager.activate(.record)
        let input = engine.inputNode
        let inFormat = input.outputFormat(forBus: 0)
        guard inFormat.sampleRate > 0, inFormat.channelCount > 0,
              let outFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16_000,
                                            channels: 1, interleaved: false),
              let converter = AVAudioConverter(from: inFormat, to: outFormat)
        else { throw AudioError.noInput }
        converter.downmix = true
        let ratio = 16_000 / inFormat.sampleRate

        input.installTap(onBus: 0, bufferSize: 4096, format: inFormat) { buffer, _ in
            let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio + 64)
            guard let out = AVAudioPCMBuffer(pcmFormat: outFormat, frameCapacity: capacity) else { return }
            var supplied = false
            var error: NSError?
            converter.convert(to: out, error: &error) { _, status in
                if supplied {
                    status.pointee = .noDataNow
                    return nil
                }
                supplied = true
                status.pointee = .haveData
                return buffer
            }
            guard error == nil, let channel = out.floatChannelData?[0], out.frameLength > 0 else { return }
            onSamples(Array(UnsafeBufferPointer(start: channel, count: Int(out.frameLength))))
        }
        engine.prepare()
        try engine.start()
    }

    func stop() {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
    }
}

/// Audio of other apps, recorded by the broadcast extension into the shared ring buffer.
final class SystemAudioSource {
    private let ring: SharedAudioRing
    private var timer: DispatchSourceTimer?
    private var position: UInt64

    init() throws {
        guard let url = SharedAudioRing.fileURL(), let ring = SharedAudioRing(url: url) else {
            throw AudioError.noAppGroup
        }
        self.ring = ring
        position = ring.written // start with what comes next
    }

    /// True while the broadcast extension has written audio in the last 2 seconds.
    var isReceiving: Bool { Date().timeIntervalSince1970 - ring.heartbeat < 2 }

    func start(queue: DispatchQueue, onSamples: @escaping ([Float]) -> Void) {
        let t = DispatchSource.makeTimerSource(queue: queue)
        t.schedule(deadline: .now() + .milliseconds(100), repeating: .milliseconds(100))
        t.setEventHandler { [weak self] in
            guard let self else { return }
            let samples = self.ring.read(from: &self.position)
            if !samples.isEmpty { onSamples(samples) }
        }
        t.resume()
        timer = t
    }

    func stop() {
        timer?.cancel()
        timer = nil
    }
}

/// Plays silence so iOS keeps the app running in the background while it transcribes the
/// audio of another app (requires the "audio" background mode).
final class KeepAlivePlayer {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()

    func start() throws {
        try AudioSessionManager.activate(.playback)
        guard let format = AVAudioFormat(standardFormatWithSampleRate: 44_100, channels: 1),
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 44_100)
        else { return }
        buffer.frameLength = 44_100
        if let channel = buffer.floatChannelData?[0] {
            channel.update(repeating: 0, count: Int(buffer.frameLength))
        }
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: format)
        player.scheduleBuffer(buffer, at: nil, options: .loops)
        try engine.start()
        player.play()
    }

    func stop() {
        player.stop()
        engine.stop()
    }
}

/// Decodes any audio or video file to 16 kHz mono floats.
enum FileAudioLoader {
    static func load(_ url: URL) async throws -> [Float] {
        let asset = AVURLAsset(url: url)
        let tracks = try await asset.loadTracks(withMediaType: .audio)
        guard let track = tracks.first else { throw AudioError.noAudioTrack }
        let reader = try AVAssetReader(asset: asset)
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 32,
            AVLinearPCMIsFloatKey: true,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false,
        ]
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: settings)
        output.alwaysCopiesSampleData = false
        reader.add(output)
        reader.startReading()
        var samples: [Float] = []
        while let sb = output.copyNextSampleBuffer() {
            guard let block = CMSampleBufferGetDataBuffer(sb) else { continue }
            let length = CMBlockBufferGetDataLength(block)
            var chunk = [Float](repeating: 0, count: length / MemoryLayout<Float>.size)
            chunk.withUnsafeMutableBytes { buffer in
                _ = CMBlockBufferCopyDataBytes(block, atOffset: 0, dataLength: buffer.count,
                                               destination: buffer.baseAddress!)
            }
            samples += chunk
        }
        if reader.status == .failed, let error = reader.error { throw error }
        return samples
    }
}
