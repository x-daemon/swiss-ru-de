import Foundation
import SwiftUI
import Translation

protocol Translating {
    func translate(_ text: String, context: [String]) async throws -> String
}

struct TranslationFailure: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

// MARK: - Claude

/// Best quality: uses the previous sentences as context, fixes obvious recognition errors and
/// leftover dialect words. Needs an Anthropic API key (Settings).
struct ClaudeTranslator: Translating {
    let apiKey: String
    let model: String
    let dialectDescription: String?

    private static let system = """
    You translate live subtitles into Russian.

    The audio is Swiss German. A speech recogniser has already converted it into Standard German, \
    sentence by sentence. Its output can contain recognition mistakes, missing punctuation, or \
    dialect words it did not convert (for example: öppis, gsi, lueg, äbe, gäll, merci vilmal, \
    Chuchichäschtli, Grüessech, Grüezi, ade, hoi, zäme, nöd, nüt, chli, gönd, gang).

    Translate only the text under "Translate:" into natural, fluent Russian.
    - Use the earlier lines only as context; do not translate them again.
    - If a word was clearly misrecognised, translate what the speaker most likely meant.
    - Keep names, places, companies and numbers. Keep Swiss terms that have no Russian equivalent \
    in their usual form (e.g. Rösti -> рёшти).
    - Reply with the Russian translation only: no quotes, notes, or explanations.
    """

    /// Models that take output_config.effort and the server-side refusal fallback.
    private static let fallbackModels: Set<String> = ["claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"]
    private static func supportsEffort(_ model: String) -> Bool {
        model.range(of: #"^claude-(opus|sonnet|haiku|fable|mythos)-5|^claude-(opus-4-[678]|sonnet-4-6)"#,
                    options: .regularExpression) != nil
    }

    func translate(_ text: String, context: [String]) async throws -> String {
        guard !apiKey.isEmpty else { throw TranslationFailure(message: "Add your Anthropic API key in Settings.") }
        var system = Self.system
        if let dialectDescription { system += "\n\nThe speaker most likely speaks \(dialectDescription)." }
        var prompt = ""
        if !context.isEmpty { prompt += "Earlier lines (context only):\n" + context.joined(separator: "\n") + "\n\n" }
        prompt += "Translate:\n" + text

        var body: [String: Any] = [
            "model": model,
            "max_tokens": 4096,
            "system": system,
            "messages": [["role": "user", "content": prompt]],
        ]
        if Self.supportsEffort(model) { body["output_config"] = ["effort": "low"] } // low = fastest

        var request = URLRequest(url: URL(string: "https://api.anthropic.com/v1/messages")!)
        request.httpMethod = "POST"
        request.timeoutInterval = 30
        request.setValue("application/json", forHTTPHeaderField: "content-type")
        request.setValue(apiKey, forHTTPHeaderField: "x-api-key")
        request.setValue("2026-10-21", forHTTPHeaderField: "anthropic-version")
        if Self.fallbackModels.contains(model) {
            // if a request is declined, the API retries it on a fallback model
            request.setValue("server-side-fallback-2026-07-01", forHTTPHeaderField: "anthropic-beta")
            body["fallbacks"] = "default"
        }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        guard status == 200, let json else {
            let message = ((json?["error"] as? [String: Any])?["message"] as? String) ?? "HTTP \(status)"
            switch status {
            case 401: throw TranslationFailure(message: "Anthropic API key is invalid.")
            case 429: throw TranslationFailure(message: "Claude rate limit reached, try again shortly.")
            default: throw TranslationFailure(message: "Claude: \(message)")
            }
        }
        if json["stop_reason"] as? String == "refusal" { return "" }
        let blocks = json["content"] as? [[String: Any]] ?? []
        return blocks.filter { $0["type"] as? String == "text" }
            .compactMap { $0["text"] as? String }
            .joined()
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

// MARK: - DeepL

struct DeepLTranslator: Translating {
    let apiKey: String

    func translate(_ text: String, context: [String]) async throws -> String {
        guard !apiKey.isEmpty else { throw TranslationFailure(message: "Add your DeepL API key in Settings.") }
        let host = apiKey.hasSuffix(":fx") ? "api-free.deepl.com" : "api.deepl.com"
        var request = URLRequest(url: URL(string: "https://\(host)/v2/translate")!)
        request.httpMethod = "POST"
        request.timeoutInterval = 20
        request.setValue("application/json", forHTTPHeaderField: "content-type")
        request.setValue("DeepL-Auth-Key \(apiKey)", forHTTPHeaderField: "authorization")
        var body: [String: Any] = ["text": [text], "source_lang": "DE", "target_lang": "RU"]
        if !context.isEmpty { body["context"] = context.joined(separator: " ") }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200,
              let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let translations = json["translations"] as? [[String: Any]],
              let first = translations.first?["text"] as? String
        else {
            switch status {
            case 403: throw TranslationFailure(message: "DeepL API key is invalid.")
            case 456: throw TranslationFailure(message: "DeepL quota used up for this month.")
            default: throw TranslationFailure(message: "DeepL error (HTTP \(status)).")
            }
        }
        return first
    }
}

// MARK: - Apple (on device)

/// Apple's on-device Translation framework: free, private, works offline once the German and
/// Russian languages are downloaded. Its session lives in a SwiftUI view (`.translationTask`),
/// so requests are queued here and served by that view.
@MainActor
final class AppleTranslationBridge: ObservableObject, Translating {
    @Published private(set) var configuration: TranslationSession.Configuration?

    private struct Request {
        let text: String
        let reply: CheckedContinuation<String, Error>
    }

    private var pending: [Request] = []

    func activate() {
        if configuration == nil {
            configuration = TranslationSession.Configuration(source: Locale.Language(identifier: "de"),
                                                            target: Locale.Language(identifier: "ru"))
        }
    }

    func translate(_ text: String, context: [String]) async throws -> String {
        activate()
        return try await withCheckedThrowingContinuation { continuation in
            pending.append(Request(text: text, reply: continuation))
        }
    }

    /// Called from `.translationTask`; runs while the view exists.
    func serve(_ session: TranslationSession) async {
        do {
            try await session.prepareTranslation() // asks to download the languages if needed
        } catch {
            failAll(error)
        }
        while !Task.isCancelled {
            guard !pending.isEmpty else {
                try? await Task.sleep(nanoseconds: 80_000_000)
                continue
            }
            let request = pending.removeFirst()
            do {
                let response = try await session.translate(request.text)
                request.reply.resume(returning: response.targetText)
            } catch {
                request.reply.resume(throwing: TranslationFailure(
                    message: "Apple translation: \(error.localizedDescription)"))
            }
        }
    }

    private func failAll(_ error: Error) {
        let failure = TranslationFailure(message: "Apple translation unavailable: \(error.localizedDescription)")
        pending.forEach { $0.reply.resume(throwing: failure) }
        pending.removeAll()
    }
}
