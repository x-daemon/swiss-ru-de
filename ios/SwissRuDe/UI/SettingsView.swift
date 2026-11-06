import ReplayKit
import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Picker("Show", selection: $settings.target) {
                        ForEach(TargetLanguage.allCases) { Text($0.title).tag($0) }
                    }
                    .pickerStyle(.segmented)
                } header: {
                    Text("Bottom part")
                } footer: {
                    Text("Русский: translation. Hochdeutsch: Standard German, no translation needed.")
                }

                Section {
                    Picker("Show", selection: $settings.top) {
                        ForEach(TopPane.allCases) { Text($0.title).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    Picker("Dialect", selection: $settings.dialect) {
                        ForEach(Dialect.all) { Text($0.label).tag($0.id) }
                    }
                } header: {
                    Text("Top part")
                } footer: {
                    Text("“Dialect as spoken” runs the speech model a second time, guided by an example text in the chosen dialect. Swiss German has no fixed spelling, so it is an approximation. The dialect choice also helps Claude translate.")
                }

                Section {
                    Picker("Translator", selection: $settings.translator) {
                        ForEach(TranslatorKind.allCases) { Text($0.title).tag($0) }
                    }
                    if settings.translator == .claude {
                        SecureField("Anthropic API key", text: $settings.claudeKey)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                        TextField("Claude model", text: $settings.claudeModel)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    }
                    if settings.translator == .deepl {
                        SecureField("DeepL API key", text: $settings.deeplKey)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    }
                } header: {
                    Text("Translation to Russian")
                } footer: {
                    Text(translatorFooter)
                }

                Section {
                    HStack {
                        Text("Font size")
                        Slider(value: $settings.fontSize, in: 13...34, step: 1)
                        Text("\(Int(settings.fontSize))").monospacedDigit().foregroundStyle(.secondary)
                    }
                    Stepper("Sentence pause: \(settings.pauseMs) ms", value: $settings.pauseMs, in: 300...1500, step: 100)
                } header: {
                    Text("Display")
                } footer: {
                    Text("A shorter pause shows sentences sooner but cuts them more often.")
                }

                Section {
                    TextField("Model", text: $settings.modelName)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    TextField("Hugging Face repo", text: $settings.modelRepo)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Toggle("Separate model for the dialect line", isOn: $settings.separateDialectModel)
                    if settings.separateDialectModel {
                        TextField("Dialect model", text: $settings.dialectModelName)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                        TextField("Dialect model repo", text: $settings.dialectModelRepo)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    }
                    Button("Load these models") {
                        Task { await model.loadModels() }
                        dismiss()
                    }
                    Button("Reset to default model") {
                        settings.modelName = AppSettings.defaultModel
                        settings.modelRepo = AppSettings.defaultRepo
                        settings.separateDialectModel = false
                    }
                } header: {
                    Text("Speech model (on this iPhone)")
                } footer: {
                    Text("Default: Whisper large-v3 turbo (626 MB) from argmaxinc/whisperkit-coreml. A Swiss German fine-tune converted to Core ML (see README) gives better Standard German; then turn on a separate dialect model and keep the default for the dialect line.")
                }

                Section("About") {
                    Text("Microphone: listens to a laptop, TV or people in the room.\niPhone audio: tap the broadcast button next to Start and choose “Swiss RU-DE Audio” to transcribe YouTube, Safari, podcasts and other apps on this iPhone. With “Floating captions” the subtitles stay visible over other apps.\nAsk everyone before you transcribe a conversation.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .preferredColorScheme(.dark)
    }

    private var translatorFooter: String {
        switch settings.translator {
        case .apple:
            return "Runs on the iPhone, free and private. The first time, iOS asks to download German and Russian."
        case .claude:
            return "Best quality: uses the earlier sentences and fixes recognition errors. Key from console.anthropic.com; stored in the iPhone Keychain."
        case .deepl:
            return "Very good and fast. The free key (ending in :fx) covers 500 000 characters per month."
        }
    }
}

/// The system button that starts the "iPhone audio" broadcast extension.
struct BroadcastPicker: UIViewRepresentable {
    func makeUIView(context: Context) -> RPSystemBroadcastPickerView {
        let picker = RPSystemBroadcastPickerView(frame: CGRect(x: 0, y: 0, width: 46, height: 46))
        picker.preferredExtension = Bundle.main.object(forInfoDictionaryKey: "BroadcastExtensionID") as? String
        picker.showsMicrophoneButton = false
        for case let button as UIButton in picker.subviews {
            button.tintColor = .white
            button.imageView?.tintColor = .white
        }
        return picker
    }

    func updateUIView(_ uiView: RPSystemBroadcastPickerView, context: Context) {}
}
