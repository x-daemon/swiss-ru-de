import Foundation

/// Dialect hints. The prompt is a short example text in that dialect; Whisper imitates the
/// writing style of its prompt, so the "as spoken" line comes out in dialect spelling.
/// (Same texts as the desktop version, swiss_ru_de/asr.py.)
struct Dialect: Identifiable, Hashable {
    let id: String
    let label: String
    let description: String?
    let prompt: String

    static let all: [Dialect] = [
        Dialect(id: "auto", label: "Automatic", description: nil,
                prompt: "Grüezi mitenand. Hüt isch es schöns Wätter, mir gönd am Namittag no chli go laufe. Weisch, das han i nöd gwüsst."),
        Dialect(id: "bern", label: "Bern", description: "Bernese German (Bärndütsch)",
                prompt: "Grüessech mitenand. Hüt isch es schöns Wätter, mir göh am Namittag no chli ga loufe. Weisch, das hani nid gwüsst."),
        Dialect(id: "berner-oberland", label: "Berner Oberland (Grindelwald)",
                description: "Bernese Oberland dialect (Grindelwald, Interlaken, Highest Alemannic)",
                prompt: "Grüessech zäme. Hiitu ischt es schöns Wätter, mier gange am Namittag no chli ga loufe. Weischt, das han i nid gwisst."),
        Dialect(id: "basel", label: "Basel", description: "Basel German (Baseldytsch)",
                prompt: "Grüezi mitenand. Hüt isch e scheens Wätter, mir gönge am Nomidaag no e bitz go spaziere. Waisch, das hani nit gwüsst."),
        Dialect(id: "zurich", label: "Zürich", description: "Zurich German (Züritüütsch)",
                prompt: "Grüezi mitenand. Hüt isch es schöns Wätter, mir gönd am Namittag no chli go laufe. Weisch, das han i nöd gwüsst."),
        Dialect(id: "wallis", label: "Wallis", description: "Valais German (Wallisertiitsch, Highest Alemannic)",
                prompt: "Grüessu zäme. Hiitu ischt schens Wätter, wier gän am Namittag no as bitzji ga loufu. Weischt, das hani nit gwisst."),
        Dialect(id: "luzern", label: "Luzern / Zentralschweiz", description: "Central Swiss German (Lucerne, Zug, Schwyz, Uri)",
                prompt: "Grüezi mitenand. Hött esch es schöns Wätter, mer gönd am Nomittag no chli go laufe. Wäisch, das hani ned gwüsst."),
        Dialect(id: "ostschweiz", label: "Ostschweiz", description: "Eastern Swiss German (St. Gallen, Thurgau, Appenzell)",
                prompt: "Grüezi mitenand. Hüt isch es schöös Wetter, mir gönd am Namittag no chli go laufe. Weisch, da han i nöd gwüsst."),
        Dialect(id: "graubuenden", label: "Graubünden", description: "Grisons German (Bündnerdeutsch)",
                prompt: "Grüezi mitanand. Hüt isch as schöns Wätter, miar gönd am Namitag no a bitz go laufa. Weisch, das han i nid gwüsst."),
        Dialect(id: "aargau", label: "Aargau", description: "Aargau German",
                prompt: "Grüezi mitenand. Hüt isch es schöns Wätter, mer gönd am Namittag no chli go laufe. Weisch, das hani ned gwüsst."),
        Dialect(id: "solothurn", label: "Solothurn", description: "Solothurn German",
                prompt: "Grüessech mitenand. Hüt isch es schöns Wätter, mir göi am Namittag no chli go laufe. Weisch, das hani nid gwüsst."),
    ]

    static func find(_ id: String) -> Dialect { all.first { $0.id == id } ?? all[0] }
}

enum TextFilters {
    /// Phrases Whisper invents on silence or music (learned from TV subtitles).
    private static let hallucinations: [NSRegularExpression] = [
        #"untertitel(ung)?\s+(im auftrag|von|der|des|durch)\b"#,
        #"untertitel(ung)?.{0,40}\b(zdf|ard|wdr|swr|ndr|mdr|br|srf|amara|funk)\b"#,
        #"\b(copyright|©)\s*(zdf|ard|wdr|swr|ndr|mdr|br|srf)\b"#,
        #"^\W*(vielen\s+)?dank\s+(fürs|für's|für das|für ihr)\s+zu(schauen|hören|sehen)\W*$"#,
        #"^\W*(das war'?s|bis zum nächsten mal)\W*(für heute)?\W*$"#,
        #"abonnier(t|en|e)\b.{0,30}\bkanal"#,
        #"^\W*(musik|applaus|lachen|stille)\W*$"#,
    ].compactMap { try? NSRegularExpression(pattern: $0, options: [.caseInsensitive]) }

    private static let specialTokens = try! NSRegularExpression(pattern: #"<\|[^|>]*\|>"#)
    private static let repeats = try! NSRegularExpression(pattern: #"(\b.{3,}?)(?:[\s,.]+\1\b){2,}"#,
                                                          options: [.caseInsensitive])

    static func isHallucination(_ text: String) -> Bool {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t.rangeOfCharacter(from: .alphanumerics) != nil else { return true }
        let range = NSRange(t.startIndex..., in: t)
        return hallucinations.contains { $0.firstMatch(in: t, range: range) != nil }
    }

    /// Removes special tokens, normalises whitespace, collapses "a, a, a, a" loops.
    static func clean(_ text: String) -> String {
        var t = specialTokens.stringByReplacingMatches(in: text, range: NSRange(text.startIndex..., in: text),
                                                       withTemplate: "")
        t = t.components(separatedBy: .whitespacesAndNewlines).filter { !$0.isEmpty }.joined(separator: " ")
        t = repeats.stringByReplacingMatches(in: t, range: NSRange(t.startIndex..., in: t), withTemplate: "$1")
        return t.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// On silence Whisper sometimes just repeats its prompt.
    static func echoesPrompt(_ text: String, prompt: String) -> Bool {
        func norm(_ s: String) -> String {
            var kept = String.UnicodeScalarView()
            for u in s.lowercased().unicodeScalars where CharacterSet.alphanumerics.contains(u) || u == " " {
                kept.append(u)
            }
            return String(kept).trimmingCharacters(in: .whitespaces)
        }
        let t = norm(text)
        return t.count > 3 && norm(prompt).contains(t)
    }
}
