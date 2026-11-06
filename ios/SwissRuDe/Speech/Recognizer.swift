import CoreML
import Foundation
import WhisperKit

/// On-device speech recognition with WhisperKit (Core ML, Neural Engine).
///
/// * `transcribeGerman` - Standard German text (meaning; input for the translation)
/// * `transcribeDialect` - the same audio written "as spoken", steered by a dialect prompt
///
/// Both use the same model unless a separate dialect model is configured.
actor Recognizer {
    struct ModelChoice: Equatable {
        var name: String
        var repo: String
    }

    private var german: WhisperKit?
    private var dialect: WhisperKit?
    private var loaded: (ModelChoice, ModelChoice?)?

    var isLoaded: Bool { german != nil }

    func load(_ model: ModelChoice, dialectModel: ModelChoice?,
              progress: @escaping @Sendable (String, Double) -> Void) async throws {
        if let loaded, loaded.0 == model, loaded.1 == dialectModel, german != nil { return }
        german = nil
        dialect = nil
        let main = try await Self.makePipe(model, label: "speech model", progress: progress)
        german = main
        if let dialectModel, dialectModel != model {
            dialect = try await Self.makePipe(dialectModel, label: "dialect model", progress: progress)
        } else {
            dialect = main
        }
        loaded = (model, dialectModel)
    }

    private static func makePipe(_ choice: ModelChoice, label: String,
                                 progress: @escaping @Sendable (String, Double) -> Void) async throws -> WhisperKit {
        // Mel spectrogram on the CPU (not GPU) so recognition keeps working while the app is
        // in the background (iOS does not allow GPU work there); the rest uses the Neural Engine.
        let compute = ModelComputeOptions(melCompute: .cpuOnly,
                                          audioEncoderCompute: .cpuAndNeuralEngine,
                                          textDecoderCompute: .cpuAndNeuralEngine)
        let config = WhisperKitConfig(model: choice.name, modelRepo: choice.repo, computeOptions: compute,
                                      verbose: false, logLevel: .error, prewarm: false, load: false,
                                      download: false)
        let pipe = try await WhisperKit(config)
        let folder = try await WhisperKit.download(variant: choice.name, from: choice.repo) { p in
            progress("Downloading \(label) …", p.fractionCompleted)
        }
        pipe.modelFolder = folder
        progress("Preparing \(label) for this iPhone (first time only, takes a few minutes) …", 1)
        try await pipe.prewarmModels()
        try await pipe.loadModels()
        return pipe
    }

    private static func options(prompt: [Int]?) -> DecodingOptions {
        var o = DecodingOptions()
        o.task = .transcribe
        o.language = "de" // Whisper has no Swiss German language code
        o.usePrefillPrompt = true
        o.detectLanguage = false
        o.skipSpecialTokens = true
        o.withoutTimestamps = true
        o.temperature = 0
        o.temperatureFallbackCount = 3
        o.compressionRatioThreshold = 2.4
        o.logProbThreshold = -1.0
        o.noSpeechThreshold = 0.6
        o.promptTokens = prompt
        return o
    }

    private static func run(_ pipe: WhisperKit, _ audio: [Float], prompt: String?) async throws -> String {
        var tokens: [Int]?
        if let prompt, let tokenizer = pipe.tokenizer {
            tokens = tokenizer.encode(text: " " + prompt.trimmingCharacters(in: .whitespaces))
                .filter { $0 < tokenizer.specialTokens.specialTokenBegin }
        }
        let results = try await pipe.transcribe(audioArray: audio, decodeOptions: options(prompt: tokens))
        let parts = results.flatMap(\.segments)
            .filter { $0.noSpeechProb < 0.8 }
            .map { TextFilters.clean($0.text) }
            .filter { !TextFilters.isHallucination($0) }
        let text = TextFilters.clean(parts.joined(separator: " "))
        if TextFilters.isHallucination(text) { return "" }
        if let prompt, TextFilters.echoesPrompt(text, prompt: prompt) { return "" }
        return text
    }

    func transcribeGerman(_ audio: [Float]) async throws -> String {
        guard let german else { return "" }
        return try await Self.run(german, audio, prompt: nil)
    }

    func transcribeDialect(_ audio: [Float], prompt: String) async throws -> String {
        guard let dialect else { return "" }
        return try await Self.run(dialect, audio, prompt: prompt)
    }
}
