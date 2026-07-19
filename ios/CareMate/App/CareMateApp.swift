import SwiftUI

@main
struct CareMateApp: App {
    @StateObject private var model = CareMateViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView(model: model)
        }
    }
}
