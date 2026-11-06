import AVFoundation
import Foundation
import SwiftUI

/// One utterance; its parts arrive at different times (German first, then translation and
/// the dialect line).
struct Row: Identifiable, Equatable {
    let id: Int
    let start: Double
    let end: Double
    var german: String
    var dialect: String?
    var dialectPending: Bool
    var translation: String?
    var translationPending: Bool
}

enum EngineState: Equatable {
    case loading
    case ready
    case failed(String)
}

@MainActor
final class AppModel: ObservableObject {
    @Published private(set) var rows: [Row] = []
    @Published private(set) var status = "Starting …"
    @Published private(set) var engine: EngineState = .loading
    @Published private(set) var loadProgress: Double = 0
    @Published private(set) var isListening = false
    @Published private(set) var listeningTo: AudioSourceKind = .microphone
    @Published private(set) var receivingSystemAudio = false
    @Published var isPaused = false {
        didSet { capture.paused = isPaused }
    }

    let settings: AppSettings
    let apple = AppleTranslationBridge()
    let floating = FloatingCaptions()

    private let recognizer = Recognizer()
    private let capture = CaptureCoordinator()
    private var workers: [Task<Void, Never>] = []
    private var translationJobs: [(id: Int, german: String)] = []
    private var context: [String] = []
    private var nextID = 0
    private var lastError = ""
    private var startedAt = Date()

    init(settings: AppSettings) {
        self.settings = settings
        startWorkers()
        Task { await loadModels() }
    }

    // MARK: - models

    func loadModels() async {
        engine = .loading
        loadProgress = 0
        do {
            try await recognizer.load(settings.model, dialectModel: settings.dialectModel) { [weak self] label, fraction in
                Task { @MainActor in
                    self?.status = label
                    self?.loadProgress = fraction
                }
            }
            engine = .ready
            loadProgress = 1
            status = isListening ? "Listening …" : "Ready. Tap Start."
        } catch {
            engine = .failed(error.localizedDescription)
            status = "Speech model failed: \(error.localizedDescription)"
        }
    }

    // MARK: - listening

    func toggleListening() {
        isListening ? stop() : start()
    }

    func start() {
        guard engine == .ready else {
            status = "The speech model is still loading …"
            return
        }
        Task {
            let kind = settings.source
            if kind == .microphone {
                guard await AVAudioApplication.requestRecordPermission() else {
                    status = AudioError.microphoneDenied.localizedDescription
                    return
                }
            }
            do {
                try capture.start(kind, pauseMs: settings.pauseMs)
                startedAt = Date()
                isListening = true
                listeningTo = kind
                isPaused = false
                status = kind == .microphone
                    ? "Listening to the microphone …"
                    : "Waiting for iPhone audio: tap the broadcast button and start “Swiss RU-DE Audio”."
            } catch {
                status = error.localizedDescription
            }
        }
    }

    func stop() {
        capture.stop()
        isListening = false
        receivingSystemAudio = false
        status = "Stopped."
    }

    func transcribe(file url: URL) {
        guard engine == .ready else {
            status = "The speech model is still loading …"
            return
        }
        status = "Reading \(url.lastPathComponent) …"
        Task {
            let access = url.startAccessingSecurityScopedResource()
            defer { if access { url.stopAccessingSecurityScopedResource() } }
            do {
                let samples = try await FileAudioLoader.load(url)
                let minutes = Double(samples.count) / 16_000 / 60
                status = String(format: "Transcribing %@ (%.1f min) …", url.lastPathComponent, minutes)
                capture.feedFile(samples) { _ in }
            } catch {
                status = "Could not read the file: \(error.localizedDescription)"
            }
        }
    }

    func clear() {
        rows.removeAll()
        context.removeAll()
        floating.show(top: "", bottom: "")
    }

    // MARK: - pipeline

    private func startWorkers() {
        let queue = capture.queue
        workers.append(Task { [weak self] in
            while !Task.isCancelled {
                guard let batch = await queue.nextBatch() else { return }
                await self?.recognize(batch)
            }
        })
        workers.append(Task { [weak self] in
            while !Task.isCancelled {
                if let job = self?.nextTranslationJob() {
                    await self?.translate(job)
                } else {
                    try? await Task.sleep(nanoseconds: 80_000_000)
                }
            }
        })
        workers.append(Task { [weak self] in // status of the iPhone-audio broadcast
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                self?.refreshBroadcastState()
            }
        })
    }

    private func refreshBroadcastState() {
        guard isListening, listeningTo == .system else { return }
        let receiving = capture.isReceivingSystemAudio
        if receiving != receivingSystemAudio {
            receivingSystemAudio = receiving
            status = receiving ? "Listening to iPhone audio …"
                : "Waiting for iPhone audio: tap the broadcast button and start “Swiss RU-DE Audio”."
        }
    }

    private func recognize(_ batch: [Segment]) async {
        guard engine == .ready, let first = batch.first, let last = batch.last else { return }
        if batch.count > 2 { status = "Catching up …" }
        let audio = Segment.merge(batch)
        let german: String
        do {
            german = try await recognizer.transcribeGerman(audio)
        } catch {
            status = "Recognition error: \(error.localizedDescription)"
            return
        }
        guard !german.isEmpty else { return }

        let wantDialect = settings.top == .dialect
        let translate = settings.target == .ru
        let id = nextID
        nextID += 1
        rows.append(Row(id: id, start: first.start, end: last.end, german: german, dialect: nil,
                        dialectPending: wantDialect, translation: nil, translationPending: translate))
        if rows.count > 500 { rows.removeFirst(rows.count - 500) }
        if translate {
            translationJobs.append((id, german))
        } else {
            remember(german)
        }
        updateFloating()

        if wantDialect {
            let prompt = Dialect.find(settings.dialect).prompt
            let dialect = (try? await recognizer.transcribeDialect(audio, prompt: prompt)) ?? ""
            update(id) {
                $0.dialect = dialect.isEmpty ? nil : dialect
                $0.dialectPending = false
            }
        }
    }

    private func nextTranslationJob() -> (id: Int, german: String)? {
        translationJobs.isEmpty ? nil : translationJobs.removeFirst()
    }

    private func translator() -> Translating {
        switch settings.translator {
        case .apple:
            return apple
        case .claude:
            return ClaudeTranslator(apiKey: settings.claudeKey, model: settings.claudeModel,
                                    dialectDescription: Dialect.find(settings.dialect).description)
        case .deepl:
            return DeepLTranslator(apiKey: settings.deeplKey)
        }
    }

    private func translate(_ job: (id: Int, german: String)) async {
        var text = ""
        do {
            text = try await translator().translate(job.german, context: Array(context.suffix(3)))
            lastError = ""
        } catch {
            let message = error.localizedDescription
            if message != lastError { // report once, not for every line
                lastError = message
                status = message
            }
        }
        remember(job.german)
        update(job.id) {
            $0.translation = text
            $0.translationPending = false
        }
    }

    private func remember(_ german: String) {
        context.append(german)
        if context.count > 10 { context.removeFirst() }
    }

    private func update(_ id: Int, _ change: (inout Row) -> Void) {
        guard let i = rows.lastIndex(where: { $0.id == id }) else { return }
        change(&rows[i])
        updateFloating()
    }

    // MARK: - display helpers

    func topText(_ row: Row) -> (String, Bool) {
        if settings.top == .dialect {
            if row.dialectPending { return ("", true) }
            if let d = row.dialect { return (d, false) }
        }
        return (row.german, false)
    }

    func bottomText(_ row: Row) -> (String, Bool) {
        if settings.target == .de { return (row.german, false) }
        if row.translationPending { return ("", true) }
        if let t = row.translation, !t.isEmpty { return (t, false) }
        return ("(\(row.german))", false)
    }

    private func updateFloating() {
        guard floating.isEnabled, let row = rows.last else { return }
        let top = topText(row)
        let bottom = bottomText(row)
        floating.show(top: top.1 ? "…" : top.0, bottom: bottom.1 ? "…" : bottom.0)
    }

    /// Subtitles (.srt) of everything on screen.
    func transcriptSRT() -> String {
        func stamp(_ t: Double) -> String {
            let ms = Int((t * 1000).rounded())
            return String(format: "%02d:%02d:%02d,%03d", ms / 3_600_000, ms / 60_000 % 60, ms / 1000 % 60, ms % 1000)
        }
        var out = ""
        for (n, row) in rows.enumerated() {
            out += "\(n + 1)\n\(stamp(row.start)) --> \(stamp(max(row.end, row.start + 1)))\n"
            let top = topText(row).0
            let bottom = bottomText(row).0
            out += (top == bottom ? top : top + "\n" + bottom) + "\n\n"
        }
        return out
    }
}
