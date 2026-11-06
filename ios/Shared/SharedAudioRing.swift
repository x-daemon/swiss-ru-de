import Foundation

/// A ring buffer of 16 kHz mono Float32 samples in a memory-mapped file inside the App Group
/// container. The broadcast extension (one writer) records the audio of other apps (YouTube,
/// Teams, …) into it; the app (one reader) turns it into subtitles.
///
/// Layout: 64-byte header (UInt64 samples written so far, Double heartbeat time), then
/// `capacity` Float32 samples.
final class SharedAudioRing {
    static let sampleRate = 16_000
    static let capacity = 16_000 * 30 // 30 s, plenty for a reader polling every 100 ms
    private static let headerSize = 64

    private let fd: Int32
    private let base: UnsafeMutableRawPointer
    private let size: Int
    private var samples: UnsafeMutablePointer<Float> {
        (base + Self.headerSize).assumingMemoryBound(to: Float.self)
    }

    /// App Group identifier from Info.plist (key `AppGroupID`, set by the build).
    static var groupID: String? {
        guard let id = Bundle.main.object(forInfoDictionaryKey: "AppGroupID") as? String,
              !id.isEmpty, !id.contains("$(") else { return nil }
        return id
    }

    static func fileURL() -> URL? {
        guard let id = groupID,
              let dir = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: id)
        else { return nil }
        return dir.appendingPathComponent("system-audio.ring")
    }

    init?(url: URL) {
        size = Self.headerSize + Self.capacity * MemoryLayout<Float>.size
        fd = open(url.path, O_RDWR | O_CREAT, 0o644)
        guard fd >= 0 else { return nil }
        guard ftruncate(fd, off_t(size)) == 0,
              let p = mmap(nil, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0),
              p != UnsafeMutableRawPointer(bitPattern: -1)
        else {
            close(fd)
            return nil
        }
        base = p
    }

    deinit {
        munmap(base, size)
        close(fd)
    }

    /// Total samples written since the file was created.
    var written: UInt64 { base.load(fromByteOffset: 0, as: UInt64.self) }

    /// Time of the last write (seconds since 1970); used to show "broadcast running".
    var heartbeat: Double { base.load(fromByteOffset: 8, as: Double.self) }

    // MARK: writer (broadcast extension)

    func write(_ input: [Float]) {
        guard !input.isEmpty else { return }
        var w = written
        let cap = UInt64(Self.capacity)
        let s = samples
        for v in input {
            s[Int(w % cap)] = v
            w += 1
        }
        OSMemoryBarrier() // samples must be visible before the new count
        base.storeBytes(of: w, toByteOffset: 0, as: UInt64.self)
        base.storeBytes(of: Date().timeIntervalSince1970, toByteOffset: 8, as: Double.self)
    }

    // MARK: reader (app)

    /// Returns everything written after `position` and advances it. If the reader fell
    /// behind by more than the buffer, the oldest audio is skipped.
    func read(from position: inout UInt64) -> [Float] {
        let w = written
        OSMemoryBarrier()
        if w < position { position = w } // file was recreated
        let cap = UInt64(Self.capacity)
        if w - position > cap { position = w - cap }
        let count = Int(w - position)
        guard count > 0 else { return [] }
        var out = [Float](repeating: 0, count: count)
        let s = samples
        for i in 0..<count {
            out[i] = s[Int((position + UInt64(i)) % cap)]
        }
        position = w
        return out
    }
}
