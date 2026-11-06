import SwiftUI

@main
struct SwissRuDeApp: App {
    @StateObject private var model = AppModel(settings: AppSettings())

    var body: some Scene {
        WindowGroup {
            ContentView(floating: model.floating)
                .environmentObject(model)
                .environmentObject(model.settings)
                .preferredColorScheme(.dark)
        }
    }
}
