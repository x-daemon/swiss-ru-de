import Foundation

/// Streaming sample-rate converter for speech: a short box filter against aliasing, then
/// linear interpolation. Cheap enough for the memory-limited broadcast extension.
struct Resampler {
    let inRate: Double
    let outRate: Double
    private var pending: [Float] = []
    private var position: Double = 0
    private var history: [Float] = []

    init(inRate: Double, outRate: Double = 16_000) {
        self.inRate = inRate
        self.outRate = outRate
    }

    mutating func process(_ input: [Float]) -> [Float] {
        guard !input.isEmpty else { return [] }
        if abs(inRate - outRate) < 1 { return input }
        let step = inRate / outRate
        let filtered = step >= 2 ? boxFilter(input, width: Int(step.rounded())) : input
        pending.append(contentsOf: filtered)

        var out: [Float] = []
        out.reserveCapacity(Int(Double(filtered.count) / step) + 2)
        while position + 1 < Double(pending.count) {
            let i = Int(position)
            let f = Float(position - Double(i))
            out.append(pending[i] * (1 - f) + pending[i + 1] * f)
            position += step
        }
        let consumed = min(Int(position), pending.count)
        pending.removeFirst(consumed)
        position -= Double(consumed)
        return out
    }

    private mutating func boxFilter(_ x: [Float], width: Int) -> [Float] {
        let joined = history + x
        var out = [Float](repeating: 0, count: x.count)
        var sum: Float = 0
        // running mean over `width` samples ending at each output position
        let offset = joined.count - x.count
        for j in 0..<joined.count {
            sum += joined[j]
            if j >= width { sum -= joined[j - width] }
            let i = j - offset
            if i >= 0 { out[i] = sum / Float(min(width, j + 1)) }
        }
        history = Array(joined.suffix(width - 1))
        return out
    }
}
