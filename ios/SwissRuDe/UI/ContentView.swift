import SwiftUI
import UniformTypeIdentifiers

/// Two parts like the desktop window: top = Swiss German as spoken, bottom = Russian or
/// Standard German (Settings). Rows are aligned by time stamp.
struct ContentView: View {
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var settings: AppSettings
    @ObservedObject private var floatingState: FloatingCaptions
    @State private var split: CGFloat = 0.5
    @State private var showSettings = false
    @State private var importing = false

    init(floating: FloatingCaptions) {
        _floatingState = ObservedObject(wrappedValue: floating)
    }

    var body: some View {
        VStack(spacing: 8) {
            header
            GeometryReader { geo in
                let total = geo.size.height
                VStack(spacing: 0) {
                    PaneView(isTop: true)
                        .frame(height: max(90, total * split - 8))
                    Capsule()
                        .fill(Theme.border)
                        .frame(width: 44, height: 5)
                        .frame(maxWidth: .infinity, minHeight: 16)
                        .contentShape(Rectangle())
                        .gesture(DragGesture(coordinateSpace: .named("split")).onChanged { value in
                            split = min(0.85, max(0.15, value.location.y / max(total, 1)))
                        })
                    PaneView(isTop: false)
                        .frame(maxHeight: .infinity)
                }
                .coordinateSpace(name: "split")
            }
            controls
        }
        .padding(.horizontal, 10)
        .padding(.bottom, 6)
        .background(Theme.background.ignoresSafeArea())
        .background(TranslationHost(bridge: model.apple))
        .sheet(isPresented: $showSettings) {
            SettingsView()
                .environmentObject(settings)
                .environmentObject(model)
        }
        .fileImporter(isPresented: $importing, allowedContentTypes: [.audio, .movie, .audiovisualContent]) { result in
            if case let .success(url) = result { model.transcribe(file: url) }
        }
    }

    // MARK: - header

    private var dotColor: Color {
        switch model.engine {
        case .failed: return Theme.error
        case .loading: return Theme.busy
        case .ready:
            if model.isPaused { return Theme.busy }
            if model.isListening, model.listeningTo == .system, !model.receivingSystemAudio { return Theme.busy }
            return model.isListening ? Theme.ok : Theme.dim
        }
    }

    private var header: some View {
        VStack(spacing: 6) {
            HStack(spacing: 8) {
                Circle().fill(dotColor).frame(width: 9, height: 9)
                Text(model.status)
                    .font(.footnote)
                    .foregroundStyle(Theme.oldText)
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)
                // Hosts the Picture-in-Picture layer (must be on screen) - a tiny preview.
                FloatingPreview(layer: model.floating.displayLayer)
                    .frame(width: 56, height: 16)
                    .opacity(floatingState.isActive || model.floating.isEnabled ? 1 : 0.05)
                Button {
                    showSettings = true
                } label: {
                    Image(systemName: "gearshape.fill")
                        .font(.title3)
                        .foregroundStyle(Theme.text)
                        .frame(width: 36, height: 36)
                }
                .accessibilityLabel("Settings")
            }
            if model.engine == .loading {
                ProgressView(value: model.loadProgress)
                    .tint(Theme.bottomAccent)
            }
        }
        .padding(.top, 4)
    }

    // MARK: - controls

    private var controls: some View {
        HStack(spacing: 10) {
            Menu {
                Picker("Listen to", selection: $settings.source) {
                    ForEach(AudioSourceKind.allCases) { kind in
                        Label(kind.title, systemImage: kind.symbol).tag(kind)
                    }
                }
                Button {
                    importing = true
                } label: {
                    Label("Transcribe a file…", systemImage: "doc.badge.plus")
                }
            } label: {
                Image(systemName: settings.source.symbol)
                    .font(.title3)
                    .frame(width: 46, height: 46)
                    .background(Theme.button, in: RoundedRectangle(cornerRadius: 12))
            }
            .disabled(model.isListening)
            .accessibilityLabel("Audio source")

            if settings.source == .system {
                BroadcastPicker()
                    .frame(width: 46, height: 46)
                    .background(Theme.button, in: RoundedRectangle(cornerRadius: 12))
                    .accessibilityLabel("Start iPhone audio broadcast")
            }

            Button {
                model.toggleListening()
            } label: {
                Label(model.isListening ? "Stop" : "Start",
                      systemImage: model.isListening ? "stop.fill" : "waveform")
                    .font(.headline)
                    .frame(maxWidth: .infinity, minHeight: 46)
                    .background(model.isListening ? Theme.topAccent : Theme.bottomAccent,
                                in: RoundedRectangle(cornerRadius: 12))
                    .foregroundStyle(.white)
            }
            .disabled(model.engine != .ready)

            if model.isListening {
                Button {
                    model.isPaused.toggle()
                } label: {
                    Image(systemName: model.isPaused ? "play.fill" : "pause.fill")
                        .font(.title3)
                        .frame(width: 46, height: 46)
                        .background(Theme.button, in: RoundedRectangle(cornerRadius: 12))
                }
                .accessibilityLabel(model.isPaused ? "Resume" : "Pause")
            }

            Menu {
                Button {
                    model.floating.toggle()
                } label: {
                    Label(floatingState.isActive ? "Hide floating captions" : "Floating captions over other apps",
                          systemImage: "pip")
                }
                .disabled(!model.floating.isSupported)
                ShareLink(item: model.transcriptSRT(), preview: SharePreview("Transcript (.srt)")) {
                    Label("Share transcript", systemImage: "square.and.arrow.up")
                }
                Button(role: .destructive) {
                    model.clear()
                } label: {
                    Label("Clear", systemImage: "trash")
                }
            } label: {
                Image(systemName: "ellipsis")
                    .font(.title3)
                    .frame(width: 46, height: 46)
                    .background(Theme.button, in: RoundedRectangle(cornerRadius: 12))
            }
            .accessibilityLabel("More")
        }
        .foregroundStyle(Theme.text)
    }
}

/// One half of the screen.
struct PaneView: View {
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var settings: AppSettings
    let isTop: Bool

    private var accent: Color { isTop ? Theme.topAccent : Theme.bottomAccent }
    private var title: String { isTop ? settings.top.paneTitle : settings.target.paneTitle }
    private var subtitle: String { isTop ? settings.top.paneSubtitle : settings.target.paneSubtitle }
    private var placeholder: String {
        isTop ? "Swiss German appears here." : (settings.target == .ru ? "Перевод появится здесь." : "Standard German appears here.")
    }

    private func text(_ row: Row) -> (String, Bool) {
        isTop ? model.topText(row) : model.bottomText(row)
    }

    var body: some View {
        let newest = model.rows.last(where: { !text($0).1 })?.id
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                RoundedRectangle(cornerRadius: 1).fill(accent).frame(width: 4, height: 14)
                Text(title).font(.caption.weight(.bold)).foregroundStyle(accent)
                Text(subtitle).font(.caption2).foregroundStyle(Theme.dim)
            }
            .padding(.horizontal, 14)
            .padding(.top, 10)

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        if model.rows.isEmpty {
                            Text(placeholder)
                                .font(.system(size: settings.fontSize))
                                .foregroundStyle(Theme.dim)
                        }
                        ForEach(model.rows) { row in
                            let (value, pending) = text(row)
                            HStack(alignment: .firstTextBaseline, spacing: 8) {
                                Text(clock(row.start))
                                    .font(.system(size: max(10, settings.fontSize * 0.58)).monospacedDigit())
                                    .foregroundStyle(Theme.dim)
                                Text(pending ? "…" : value)
                                    .font(.system(size: settings.fontSize, weight: isTop ? .regular : .semibold))
                                    .foregroundStyle(pending ? Theme.dim : (row.id == newest ? Theme.text : Theme.oldText))
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .textSelection(.enabled)
                            }
                            .id(row.id)
                        }
                    }
                    .padding(.horizontal, 14)
                    .padding(.bottom, 12)
                }
                .onChange(of: model.rows.last) { _, last in
                    guard let last else { return }
                    withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 10))
    }

    private func clock(_ seconds: Double) -> String {
        let s = Int(seconds)
        return s >= 3600 ? String(format: "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60)
            : String(format: "%02d:%02d", s / 60, s % 60)
    }
}

/// Serves Apple translation requests (the session must live in a view).
struct TranslationHost: View {
    @ObservedObject var bridge: AppleTranslationBridge

    var body: some View {
        Color.clear
            .translationTask(bridge.configuration) { session in
                await bridge.serve(session)
            }
    }
}
