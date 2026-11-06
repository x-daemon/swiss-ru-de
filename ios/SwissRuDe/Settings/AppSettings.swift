import Foundation
import Security

enum TargetLanguage: String, CaseIterable, Identifiable {
    case ru, de

    var id: String { rawValue }
    var title: String { self == .ru ? "Русский" : "Hochdeutsch" }
    var paneTitle: String { self == .ru ? "РУССКИЙ" : "HOCHDEUTSCH" }
    var paneSubtitle: String { self == .ru ? "перевод" : "Standard German" }
}

enum TopPane: String, CaseIterable, Identifiable {
    case dialect, german

    var id: String { rawValue }
    var title: String { self == .dialect ? "Dialect as spoken" : "Standard German" }
    var paneTitle: String { self == .dialect ? "SCHWIIZERDÜTSCH" : "HOCHDEUTSCH" }
    var paneSubtitle: String { self == .dialect ? "as spoken" : "Standard German" }
}

enum TranslatorKind: String, CaseIterable, Identifiable {
    case apple, claude, deepl

    var id: String { rawValue }
    var title: String {
        switch self {
        case .apple: "Apple (on device, free)"
        case .claude: "Claude (best)"
        case .deepl: "DeepL"
        }
    }
}

/// User settings, stored in UserDefaults (API keys in the Keychain).
final class AppSettings: ObservableObject {
    static let defaultModel = "large-v3-v20240930_626MB"
    static let defaultRepo = "argmaxinc/whisperkit-coreml"
    static let defaultClaudeModel = "claude-opus-5-5"

    private let store = UserDefaults.standard

    @Published var target: TargetLanguage { didSet { store.set(target.rawValue, forKey: "target") } }
    @Published var top: TopPane { didSet { store.set(top.rawValue, forKey: "top") } }
    @Published var dialect: String { didSet { store.set(dialect, forKey: "dialect") } }
    @Published var translator: TranslatorKind { didSet { store.set(translator.rawValue, forKey: "translator") } }
    @Published var source: AudioSourceKind { didSet { store.set(source.rawValue, forKey: "source") } }
    @Published var fontSize: Double { didSet { store.set(fontSize, forKey: "fontSize") } }
    @Published var pauseMs: Int { didSet { store.set(pauseMs, forKey: "pauseMs") } }
    @Published var modelName: String { didSet { store.set(modelName, forKey: "modelName") } }
    @Published var modelRepo: String { didSet { store.set(modelRepo, forKey: "modelRepo") } }
    @Published var separateDialectModel: Bool { didSet { store.set(separateDialectModel, forKey: "separateDialectModel") } }
    @Published var dialectModelName: String { didSet { store.set(dialectModelName, forKey: "dialectModelName") } }
    @Published var dialectModelRepo: String { didSet { store.set(dialectModelRepo, forKey: "dialectModelRepo") } }
    @Published var claudeModel: String { didSet { store.set(claudeModel, forKey: "claudeModel") } }
    @Published var claudeKey: String { didSet { Keychain.set(claudeKey, for: "anthropic") } }
    @Published var deeplKey: String { didSet { Keychain.set(deeplKey, for: "deepl") } }

    init() {
        let s = UserDefaults.standard
        target = TargetLanguage(rawValue: s.string(forKey: "target") ?? "") ?? .ru
        top = TopPane(rawValue: s.string(forKey: "top") ?? "") ?? .dialect
        dialect = s.string(forKey: "dialect") ?? "auto"
        translator = TranslatorKind(rawValue: s.string(forKey: "translator") ?? "") ?? .apple
        source = AudioSourceKind(rawValue: s.string(forKey: "source") ?? "") ?? .microphone
        fontSize = s.object(forKey: "fontSize") as? Double ?? 19
        pauseMs = s.object(forKey: "pauseMs") as? Int ?? 600
        modelName = s.string(forKey: "modelName") ?? Self.defaultModel
        modelRepo = s.string(forKey: "modelRepo") ?? Self.defaultRepo
        separateDialectModel = s.bool(forKey: "separateDialectModel")
        dialectModelName = s.string(forKey: "dialectModelName") ?? Self.defaultModel
        dialectModelRepo = s.string(forKey: "dialectModelRepo") ?? Self.defaultRepo
        claudeModel = s.string(forKey: "claudeModel") ?? Self.defaultClaudeModel
        claudeKey = Keychain.get("anthropic") ?? ""
        deeplKey = Keychain.get("deepl") ?? ""
    }

    var model: Recognizer.ModelChoice {
        Recognizer.ModelChoice(name: modelName.trimmingCharacters(in: .whitespaces),
                               repo: modelRepo.trimmingCharacters(in: .whitespaces))
    }

    var dialectModel: Recognizer.ModelChoice? {
        guard separateDialectModel else { return nil }
        return Recognizer.ModelChoice(name: dialectModelName.trimmingCharacters(in: .whitespaces),
                                      repo: dialectModelRepo.trimmingCharacters(in: .whitespaces))
    }
}

enum Keychain {
    private static let service = "swiss-ru-de"

    static func get(_ account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func set(_ value: String, for account: String) {
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(base as CFDictionary)
        guard !value.isEmpty else { return }
        var add = base
        add[kSecValueData as String] = Data(value.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        SecItemAdd(add as CFDictionary, nil)
    }
}
