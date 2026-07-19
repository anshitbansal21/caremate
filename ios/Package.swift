// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "CareMateCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "CareMateCore", targets: ["CareMateCore"])],
    targets: [
        .target(name: "CareMateCore", path: "CareMate/Core"),
        .target(
            name: "CareMateAppLogic",
            dependencies: ["CareMateCore"],
            path: "CareMate/App",
            exclude: ["CareMateApp.swift", "ContentView.swift"]
        ),
        .testTarget(
            name: "CareMateCoreTests",
            dependencies: ["CareMateCore", "CareMateAppLogic"],
            path: "Tests/CareMateCoreTests"
        ),
    ]
)
