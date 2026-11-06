import Foundation

enum AudioSourceKind: String, CaseIterable, Identifiable {
    case microphone, system

    var id: String { rawValue }
    var title: String { self == .microphone ? "Microphone" : "iPhone audio" }
    var symbol: String { self == .microphone ? "mic.fill" : "iphone.radiowaves.left.and.right" }
}

/// Utterances waiting for speech recognition. Filled by the capture thread, emptied by the
/// recognition task; backlog is merged so a slow phase catches up.
final class SegmentQueue: @unchecked Sendable {
    private var items: [Segment] = []
    private let lock = NSLock()

    func push(_ segment: Segment) {
        lock.withLock { items.append(segment) }
    }

    func clear() {
        lock.withLock { items.removeAll() }
    }

    var count: Int { lock.withLock { items.count } }

    private func take(maxSeconds: Double) -> [Segment]? {
        lock.withLock {
            guard !items.isEmpty else { return nil }
            var batch = [items.removeFirst()]
            var total = batch[0].duration
            while let next = items.first, total + next.duration <= maxSeconds {
                batch.append(items.removeFirst())
                total += next.duration
            }
            return batch
        }
    }

    /// Waits for at least one utterance; returns it plus the backlog that fits in one
    /// 30 s Whisper window. Nil when the task is cancelled.
    func nextBatch(maxSeconds: Double = 25) async -> [Segment]? {
        while !Task.isCancelled {
            if let batch = take(maxSeconds: maxSeconds) { return batch }
            try? await Task.sleep(nanoseconds: 50_000_000)
        }
        return nil
    }
}

/// Owns the audio sources and the segmenter. Audio arrives on a serial queue, is cut into
/// utterances and pushed to `queue`.
final class CaptureCoordinator: @unchecked Sendable {
    let queue = SegmentQueue()
    var paused = false

    private let audioQueue = DispatchQueue(label: "swissrude.capture", qos: .userInitiated)
    private var segmenter = Segmenter()
    private var mic: MicrophoneSource?
    private var system: SystemAudioSource?
    private var keepAlive: KeepAlivePlayer?

    var isReceivingSystemAudio: Bool { system?.isReceiving ?? false }

    func start(_ kind: AudioSourceKind, pauseMs: Int) throws {
        stop()
        audioQueue.sync { segmenter = Segmenter(pauseMs: pauseMs) }
        switch kind {
        case .microphone:
            let m = MicrophoneSource()
            try m.start { [weak self] samples in self?.ingest(samples) }
            mic = m
        case .system:
            let s = try SystemAudioSource()
            let k = KeepAlivePlayer()
            try k.start()
            s.start(queue: audioQueue) { [weak self] samples in self?.feed(samples) }
            system = s
            keepAlive = k
        }
    }

    func stop() {
        mic?.stop()
        system?.stop()
        keepAlive?.stop()
        mic = nil
        system = nil
        keepAlive = nil
        audioQueue.sync {
            if let last = segmenter.flush(), !paused { queue.push(last) }
        }
    }

    /// A whole file: cut into utterances as fast as possible.
    func feedFile(_ samples: [Float], completion: @escaping (Int) -> Void) {
        audioQueue.async { [queue] in
            let s = Segmenter()
            var count = 0
            var i = 0
            let chunk = 16_000
            while i < samples.count {
                for seg in s.feed(Array(samples[i..<min(i + chunk, samples.count)])) {
                    queue.push(seg)
                    count += 1
                }
                i += chunk
            }
            if let last = s.flush() {
                queue.push(last)
                count += 1
            }
            completion(count)
        }
    }

    private func ingest(_ samples: [Float]) {
        audioQueue.async { [weak self] in self?.feed(samples) }
    }

    /// Must run on `audioQueue`.
    private func feed(_ samples: [Float]) {
        for seg in segmenter.feed(samples) where !paused {
            queue.push(seg)
        }
    }
}
