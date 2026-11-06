import Foundation

/// One utterance cut out of the audio stream.
struct Segment {
    let start: Double // seconds since the stream started
    let end: Double
    let audio: [Float] // 16 kHz mono

    var duration: Double { end - start }

    /// Joins several utterances (with short gaps) into one recognition window.
    static func merge(_ segments: [Segment]) -> [Float] {
        guard segments.count > 1 else { return segments.first?.audio ?? [] }
        let gap = [Float](repeating: 0, count: Int(0.3 * Double(Segmenter.sampleRate)))
        var out: [Float] = []
        for (i, s) in segments.enumerated() {
            if i > 0 { out += gap }
            out += s.audio
        }
        return out
    }
}

/// Cuts a continuous 16 kHz stream into utterances at pauses. Energy based, with a noise
/// floor that follows the background (10th percentile of the last 5 s). Same logic as the
/// desktop version (swiss_ru_de/segmenter.py).
final class Segmenter {
    static let sampleRate = 16_000
    private let frame = 480 // 30 ms
    private let silenceFrames: Int
    private let minSpeechFrames = 8 // 240 ms
    private let maxFrames: Int
    private let keepTailFrames = 6 // keep 180 ms of the closing pause
    private let preRollFrames = 10 // 300 ms before the onset
    private let marginDB: Float = 8
    private let floorDB: Float = -55
    private let maxNoiseDB: Float = -35
    private let historyFrames = 166 // 5 s

    private var pending: [Float] = []
    private var pre: [[Float]] = []
    private var frames: [[Float]] = []
    private var flags: [Bool] = []
    private var dbs: [Float] = []
    private var history: [Float] = []
    private var segStart = 0
    private var consumed = 0
    private var silenceRun = 0
    private(set) var inSpeech = false

    init(pauseMs: Int = 600, maxSegmentSeconds: Double = 12) {
        silenceFrames = max(1, pauseMs / 30)
        maxFrames = max(2, Int(maxSegmentSeconds * 1000 / 30))
    }

    func feed(_ audio: [Float]) -> [Segment] {
        pending += audio
        var out: [Segment] = []
        let n = pending.count / frame
        for i in 0..<n {
            let f = Array(pending[(i * frame)..<((i + 1) * frame)])
            if let seg = process(f) { out.append(seg) }
        }
        pending.removeFirst(n * frame)
        return out
    }

    func flush() -> Segment? {
        let seg = inSpeech ? emit(frames.count) : nil
        reset()
        return seg
    }

    // MARK: -

    private static func level(_ frame: [Float]) -> Float {
        var sum: Float = 0
        for v in frame { sum += v * v }
        let rms = (sum / Float(max(1, frame.count))).squareRoot()
        return max(20 * log10(rms + 1e-10), -100)
    }

    private var noiseDB: Float {
        guard !history.isEmpty else { return floorDB - marginDB }
        let sorted = history.sorted()
        let p10 = sorted[Int(Double(sorted.count - 1) * 0.1)]
        return min(p10, maxNoiseDB)
    }

    private func isSpeech(_ db: Float) -> Bool {
        let threshold = max(noiseDB + marginDB, floorDB)
        history.append(db)
        if history.count > historyFrames { history.removeFirst(history.count - historyFrames) }
        return db > threshold
    }

    private func process(_ f: [Float]) -> Segment? {
        let db = Self.level(f)
        let speech = isSpeech(db)
        let startSample = consumed
        consumed += f.count

        if !inSpeech {
            if !speech {
                pre.append(f)
                if pre.count > preRollFrames { pre.removeFirst() }
                return nil
            }
            inSpeech = true
            frames = pre
            flags = Array(repeating: false, count: pre.count)
            dbs = Array(repeating: -100, count: pre.count)
            segStart = startSample - pre.count * frame
            pre.removeAll()
            silenceRun = 0
        }

        frames.append(f)
        flags.append(speech)
        dbs.append(db)
        silenceRun = speech ? 0 : silenceRun + 1

        if silenceRun >= silenceFrames {
            let seg = emit(frames.count - silenceRun + keepTailFrames)
            reset()
            return seg
        }
        if frames.count >= maxFrames { return split() }
        return nil
    }

    /// Too long: cut at the quietest point of the last 40 %.
    private func split() -> Segment? {
        let n = frames.count
        let lo = Int(Double(n) * 0.6)
        var best = lo, bestLevel = Float.greatestFiniteMagnitude
        for i in lo..<n {
            let a = dbs[max(lo, i - 1)], b = dbs[i], c = dbs[min(n - 1, i + 1)]
            let smooth = (a + b + c) / 3
            if smooth < bestLevel { bestLevel = smooth; best = i }
        }
        let cut = min(max(best + 1, 1), n - 1)
        let seg = emit(cut)
        segStart += cut * frame
        frames.removeFirst(cut)
        flags.removeFirst(cut)
        dbs.removeFirst(cut)
        return seg
    }

    private func emit(_ count: Int) -> Segment? {
        let k = min(max(0, count), frames.count)
        guard k > 0, flags[0..<k].filter({ $0 }).count >= minSpeechFrames else { return nil }
        let audio = frames[0..<k].flatMap { $0 }
        let start = Double(segStart) / Double(Self.sampleRate)
        return Segment(start: start, end: start + Double(audio.count) / Double(Self.sampleRate), audio: audio)
    }

    private func reset() {
        inSpeech = false
        frames.removeAll()
        flags.removeAll()
        dbs.removeAll()
        silenceRun = 0
    }
}
