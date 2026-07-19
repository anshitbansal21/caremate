import SwiftUI
import UIKit
import OSLog

private let cameraFeedLogger = Logger(
    subsystem: "com.caremate.prototype",
    category: "CameraFeed"
)

struct ContentView: View {
    @ObservedObject var model: CareMateViewModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var selectedTab: AppTab = .overview

    var body: some View {
        TabView(selection: $selectedTab) {
            OverviewScreen(model: model, selectedTab: $selectedTab)
                .tag(AppTab.overview)
                .tabItem {
                    Label("Overview", systemImage: "house.fill")
                }

            LiveViewScreen(model: model)
                .tag(AppTab.live)
                .tabItem {
                    Label("Live View", systemImage: "video.fill")
                }

            SystemScreen(model: model)
                .tag(AppTab.system)
                .tabItem {
                    Label("System", systemImage: "waveform.path.ecg")
                }
        }
        .tint(CareMateTheme.accent)
        .onChange(of: scenePhase) { _, phase in
            model.setForeground(phase == .active)
        }
    }
}

private enum AppTab: Hashable {
    case overview
    case live
    case system
}

private enum CareMateTheme {
    static let accent = Color(red: 0.08, green: 0.42, blue: 0.55)
    static let deepBlue = Color(red: 0.06, green: 0.19, blue: 0.28)
    static let pageBackground = Color(uiColor: .systemGroupedBackground)
}

private struct OverviewScreen: View {
    @ObservedObject var model: CareMateViewModel
    @Binding var selectedTab: AppTab

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(spacing: 16) {
                    if model.status == nil {
                        WelcomeCard()
                        ConnectionCard(model: model)
                    } else {
                        StatusHero(model: model)

                        if let fall = model.activeFall {
                            FallAlertCard(model: model, fall: fall)
                        }

                        QuickActions(model: model, selectedTab: $selectedTab)

                        if let analysis = model.analysis {
                            CompactAnalysisCard(
                                analysis: analysis,
                                summary: model.analysisSummary?.paragraph
                            ) {
                                selectedTab = .live
                            }
                        }
                    }

                    PrototypeNotice()
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
            }
            .background(CareMateTheme.pageBackground)
            .navigationTitle("CareMate")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    ConnectionBadge(model: model)
                }
            }
        }
    }
}

private struct WelcomeCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            ZStack {
                Circle()
                    .fill(.white.opacity(0.14))
                    .frame(width: 58, height: 58)
                Image(systemName: "heart.text.square.fill")
                    .font(.system(size: 28))
                    .foregroundStyle(.white)
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("Connect to your CareMate hub")
                    .font(.title2.bold())
                Text("View live activity, receive possible-fall updates, and request a fresh room analysis.")
                    .font(.subheadline)
                    .foregroundStyle(.white.opacity(0.82))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(22)
        .background(
            LinearGradient(
                colors: [CareMateTheme.deepBlue, CareMateTheme.accent],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        )
        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        .shadow(color: CareMateTheme.deepBlue.opacity(0.16), radius: 16, y: 8)
    }
}

private struct StatusHero: View {
    @ObservedObject var model: CareMateViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("CURRENT ACTIVITY")
                        .font(.caption.weight(.bold))
                        .tracking(1.2)
                        .foregroundStyle(.white.opacity(0.66))
                    Text(model.currentActivity.label)
                        .font(.system(.largeTitle, design: .rounded, weight: .bold))
                    if model.analysis == nil || model.analysis?.uncertain == true {
                        Label("Run Analyze space for a current observation", systemImage: "questionmark.circle.fill")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(Color.yellow.opacity(0.95))
                    }
                }

                Spacer(minLength: 12)

                ZStack {
                    Circle()
                        .fill(.white.opacity(0.12))
                        .frame(width: 64, height: 64)
                    Image(systemName: activityIcon(model.currentActivity))
                        .font(.system(size: 30, weight: .medium))
                }
            }

            Divider().overlay(.white.opacity(0.18))

            HStack(spacing: 10) {
                Label(model.isStale ? "Status is stale" : "Monitoring live", systemImage: model.isStale ? "clock.badge.exclamationmark" : "dot.radiowaves.left.and.right")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(model.isStale ? Color.yellow : Color.white)

                Spacer()

                if let lastUpdated = model.lastUpdated {
                    Text(lastUpdated, style: .relative)
                        .font(.caption)
                        .foregroundStyle(.white.opacity(0.65))
                }
            }
        }
        .foregroundStyle(.white)
        .padding(22)
        .background(
            LinearGradient(
                colors: [CareMateTheme.deepBlue, CareMateTheme.accent],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        )
        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        .shadow(color: CareMateTheme.deepBlue.opacity(0.18), radius: 18, y: 8)
        .accessibilityElement(children: .combine)
    }

    private func activityIcon(_ state: PersonState?) -> String {
        switch state {
        case .onBed: "bed.double.fill"
        case .standing: "figure.stand"
        case .sitting: "figure.seated.seatbelt"
        case .lying: "figure.fall"
        case .walking: "figure.walk"
        case .notVisible: "person.slash.fill"
        case .uncertain, nil: "person.fill.questionmark"
        }
    }
}

private struct QuickActions: View {
    @ObservedObject var model: CareMateViewModel
    @Binding var selectedTab: AppTab

    var body: some View {
        HStack(spacing: 12) {
            QuickActionButton(
                title: "Live camera",
                subtitle: "Annotated feed",
                systemImage: "video.fill",
                color: CareMateTheme.accent
            ) {
                selectedTab = .live
            }

            QuickActionButton(
                title: model.isAnalyzing ? "Analyzing…" : "Analyze space",
                subtitle: "Fresh room check",
                systemImage: "viewfinder",
                color: .indigo,
                isBusy: model.isAnalyzing
            ) {
                Task { await model.analyzeSpace() }
            }
            .disabled(model.isAnalyzing)
        }
    }
}

private struct QuickActionButton: View {
    let title: String
    let subtitle: String
    let systemImage: String
    let color: Color
    var isBusy = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: 11, style: .continuous)
                        .fill(color.opacity(0.12))
                        .frame(width: 42, height: 42)
                    if isBusy {
                        ProgressView().tint(color)
                    } else {
                        Image(systemName: systemImage)
                            .font(.system(size: 18, weight: .semibold))
                            .foregroundStyle(color)
                    }
                }

                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.primary)
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .background(Color(uiColor: .secondarySystemGroupedBackground))
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(Color.primary.opacity(0.05))
            }
        }
        .buttonStyle(.plain)
    }
}

private struct LiveViewScreen: View {
    @ObservedObject var model: CareMateViewModel

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(spacing: 16) {
                    LiveFeedCard(model: model)
                    AnalyzeActionCard(model: model)

                    if let analysis = model.analysis {
                        AnalysisResultCard(
                            analysis: analysis,
                            summary: model.analysisSummary,
                            isGeneratingSummary: model.isGeneratingSummary
                        )
                    }

                    PrivacyNotice()
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
            }
            .background(CareMateTheme.pageBackground)
            .navigationTitle("Live View")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    ConnectionBadge(model: model)
                }
            }
        }
    }
}

private struct LiveFeedCard: View {
    @ObservedObject var model: CareMateViewModel
    @State private var loggedDecodeFailure = false

    var body: some View {
        VStack(spacing: 0) {
            ZStack(alignment: .topLeading) {
                Group {
                    if let data = model.frameData, let image = UIImage(data: data) {
                        Image(uiImage: image)
                            .resizable()
                            .scaledToFit()
                            .accessibilityLabel("Latest annotated camera frame")
                    } else {
                        VStack(spacing: 12) {
                            ContentUnavailableView(
                                "Feed unavailable",
                                systemImage: "video.slash.fill",
                                description: Text(feedUnavailableMessage)
                            )
                            Button {
                                Task { await model.loadSingleFrame() }
                            } label: {
                                if model.isLoadingSingleFrame {
                                    ProgressView()
                                } else {
                                    Label("Load one frame", systemImage: "photo")
                                }
                            }
                            .buttonStyle(.bordered)
                            .disabled(model.status == nil || model.isLoadingSingleFrame)
                        }
                    }
                }
                .frame(maxWidth: .infinity, minHeight: 240)
                .background(Color(uiColor: .secondarySystemBackground))

                if model.frameData != nil {
                    Label("LIVE", systemImage: "circle.fill")
                        .font(.caption2.bold())
                        .foregroundStyle(.white)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 7)
                        .background(.black.opacity(0.64), in: Capsule())
                        .padding(12)
                }
            }

            HStack(spacing: 12) {
                Image(systemName: "sparkles.rectangle.stack.fill")
                    .foregroundStyle(CareMateTheme.accent)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Annotated camera feed")
                        .font(.subheadline.weight(.semibold))
                    Text("Updated from the stationary vision hub")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if model.isStale {
                    Text("STALE")
                        .font(.caption2.bold())
                        .foregroundStyle(.orange)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 5)
                        .background(.orange.opacity(0.12), in: Capsule())
                }
            }
            .padding(16)
        }
        .onChange(of: model.frameData) { _, data in
            guard let data else {
                loggedDecodeFailure = false
                return
            }
            if UIImage(data: data) == nil {
                if !loggedDecodeFailure {
                    cameraFeedLogger.error(
                        "UIKit could not decode camera frame bytes=\(data.count)"
                    )
                    loggedDecodeFailure = true
                }
            } else {
                loggedDecodeFailure = false
            }
        }
        .background(Color(uiColor: .secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .stroke(Color.primary.opacity(0.06))
        }
        .shadow(color: .black.opacity(0.05), radius: 10, y: 4)
    }

    private var feedUnavailableMessage: String {
        if model.status == nil {
            return "Connect to the hub from the Overview or System tab."
        }
        if let error = model.feedError {
            return "Feed connection failed: \(error)"
        }
        return "Waiting for a fresh annotated frame from the hub."
    }
}

private struct AnalyzeActionCard: View {
    @ObservedObject var model: CareMateViewModel

    var body: some View {
        CareCard {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .top, spacing: 12) {
                    CardIcon(systemImage: "viewfinder", color: .indigo)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Space analysis")
                            .font(.headline)
                        Text("Request a fresh frame and a concise activity and room summary.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }

                Button {
                    Task { await model.analyzeSpace() }
                } label: {
                    HStack {
                        if model.isAnalyzing {
                            ProgressView().tint(.white)
                        } else {
                            Image(systemName: "sparkles")
                        }
                        Text(model.isAnalyzing ? "Analyzing latest frame…" : "Analyze space")
                    }
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 4)
                }
                .buttonStyle(.borderedProminent)
                .tint(.indigo)
                .controlSize(.large)
                .disabled(model.isAnalyzing || model.status == nil)
            }
        }
    }
}

private struct CompactAnalysisCard: View {
    let analysis: SpaceAnalysis
    let summary: String?
    let showDetails: () -> Void

    var body: some View {
        Button(action: showDetails) {
            CareCard {
                HStack(spacing: 14) {
                    CardIcon(
                        systemImage: analysis.uncertain ? "questionmark.circle.fill" : "sparkles",
                        color: analysis.uncertain ? .orange : .indigo
                    )
                    VStack(alignment: .leading, spacing: 5) {
                        Text("Latest analysis")
                            .font(.headline)
                            .foregroundStyle(.primary)
                        Text(summary ?? analysis.roomSummary)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                    Spacer(minLength: 8)
                    Image(systemName: "chevron.right")
                        .font(.caption.bold())
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .buttonStyle(.plain)
    }
}

private struct AnalysisResultCard: View {
    let analysis: SpaceAnalysis
    let summary: AnalysisPresentationSummary?
    let isGeneratingSummary: Bool

    var body: some View {
        CareCard {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top, spacing: 12) {
                    CardIcon(
                        systemImage: analysis.uncertain ? "questionmark.circle.fill" : "checkmark.circle.fill",
                        color: analysis.uncertain ? .orange : CareMateTheme.accent
                    )
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Latest analysis")
                            .font(.headline)
                        if let capturedAt = analysis.capturedAtDate {
                            Text(capturedAt, format: .dateTime.hour().minute())
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        } else {
                            Text("Latest captured frame")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    Text(analysis.personState.label)
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 6)
                        .background(CareMateTheme.accent.opacity(0.11), in: Capsule())
                        .foregroundStyle(CareMateTheme.accent)
                }

                VStack(alignment: .leading, spacing: 8) {
                    if isGeneratingSummary {
                        HStack(spacing: 8) {
                            ProgressView()
                            Text("Generating a summary on this iPhone…")
                                .foregroundStyle(.secondary)
                        }
                    } else if let summary {
                        Text(summary.paragraph)
                            .font(.body)
                            .fixedSize(horizontal: false, vertical: true)
                        Label(
                            summary.source == .foundationModel
                                ? "Generated on this iPhone from hub observations"
                                : "Apple Intelligence unavailable — using the hub summary",
                            systemImage: summary.source == .foundationModel
                                ? "apple.intelligence"
                                : "iphone"
                        )
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                }

                Divider()

                VStack(alignment: .leading, spacing: 5) {
                    Text("HUB OBSERVATION")
                        .font(.caption.weight(.bold))
                        .tracking(0.8)
                        .foregroundStyle(.secondary)
                    Text(analysis.roomSummary)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                if !analysis.riskObservations.isEmpty {
                    Divider()
                    VStack(alignment: .leading, spacing: 10) {
                        Text("RISK OBSERVATIONS")
                            .font(.caption.weight(.bold))
                            .tracking(0.8)
                            .foregroundStyle(.secondary)
                        ForEach(analysis.riskObservations, id: \.self) { risk in
                            Label(risk, systemImage: "exclamationmark.triangle.fill")
                                .font(.subheadline)
                                .foregroundStyle(.orange)
                        }
                    }
                }

                HStack {
                    Text("Recommendation")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(analysis.alertRecommendation.capitalized)
                        .font(.subheadline.weight(.semibold))
                }

                if analysis.uncertain {
                    Label("This result is uncertain and should be checked.", systemImage: "info.circle.fill")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            }
        }
    }
}

private struct SystemScreen: View {
    @ObservedObject var model: CareMateViewModel

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(spacing: 16) {
                    ConnectionCard(model: model)
                    SystemHealthCard(model: model)

                    SessionDetailsCard(model: model)
                    PrototypeNotice()
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
            }
            .background(CareMateTheme.pageBackground)
            .navigationTitle("System")
        }
    }
}

private struct ConnectionCard: View {
    @ObservedObject var model: CareMateViewModel

    var body: some View {
        CareCard {
            VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 12) {
                    CardIcon(systemImage: "point.3.connected.trianglepath.dotted", color: CareMateTheme.accent)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Hub connection")
                            .font(.headline)
                        Text(model.connectionState.label)
                            .font(.subheadline)
                            .foregroundStyle(connectionColor)
                    }
                    Spacer()
                    Circle()
                        .fill(connectionColor)
                        .frame(width: 10, height: 10)
                        .shadow(color: connectionColor.opacity(0.45), radius: 4)
                }

                VStack(spacing: 10) {
                    InputField(systemImage: "network") {
                        TextField("Hub URL", text: $model.serverAddress)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                    }

                    InputField(systemImage: "key.fill") {
                        SecureField("Access token", text: $model.accessToken)
                            .textInputAutocapitalization(.never)
                    }
                }

                if case let .failed(message) = model.connectionState {
                    Label(message, systemImage: "exclamationmark.circle.fill")
                        .font(.caption)
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                }

                HStack(spacing: 10) {
                    Button {
                        model.connect()
                    } label: {
                        HStack {
                            if model.connectionState == .connecting {
                                ProgressView().tint(.white)
                            }
                            Text(model.status == nil ? "Connect" : "Reconnect")
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(CareMateTheme.accent)
                    .controlSize(.large)
                    .disabled(model.connectionState == .connecting)

                    if model.status != nil {
                        Button("Disconnect", role: .destructive) {
                            model.disconnect(clearData: true)
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.large)
                    }
                }

                Text("Connect saves the hub URL on this device and stores the token securely in Keychain.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var connectionColor: Color {
        switch model.connectionState {
        case .connected: .green
        case .connecting: CareMateTheme.accent
        case .failed: .orange
        case .disconnected: .secondary
        }
    }
}

private struct SystemHealthCard: View {
    @ObservedObject var model: CareMateViewModel

    var body: some View {
        CareCard {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("Hub status")
                        .font(.headline)
                    Spacer()
                    if let status = model.status {
                        Text(status.state.label)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(status.state == .fault ? .red : .green)
                            .padding(.horizontal, 9)
                            .padding(.vertical, 5)
                            .background(
                                (status.state == .fault ? Color.red : Color.green).opacity(0.1),
                                in: Capsule()
                            )
                    }
                }

                if let status = model.status {
                    DetailRow(label: "Fusion state", value: status.state.label)
                    DetailRow(label: "Alert level", value: status.level.rawValue.capitalized)
                    DetailRow(label: "Event stream", value: model.connectionState == .connected ? "Connected" : "Reconnecting")
                } else {
                    ContentUnavailableView(
                        "No hub status",
                        systemImage: "waveform.path.ecg",
                        description: Text("Connect to the hub to view its fusion and alert state.")
                    )
                    .frame(minHeight: 150)
                }
            }
        }
    }
}

private struct SessionDetailsCard: View {
    @ObservedObject var model: CareMateViewModel

    var body: some View {
        CareCard {
            VStack(alignment: .leading, spacing: 12) {
                Text("Session details")
                    .font(.headline)
                DetailRow(label: "Data source", value: model.status == nil ? "Unavailable" : "Aryan's live hub")
                DetailRow(label: "API contract", value: model.status == nil ? "Unavailable" : "SSE + REST + MJPEG")
                if let timestamp = model.status?.timestampMilliseconds {
                    DetailRow(label: "Hub timestamp", value: "\(timestamp) ms")
                }
                DetailRow(label: "Last update", value: lastUpdateText)
                if model.isStale, model.status != nil {
                    Label("Last known data is being preserved while the connection recovers.", systemImage: "clock.badge.exclamationmark")
                        .font(.caption)
                        .foregroundStyle(.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private var lastUpdateText: String {
        guard let date = model.lastUpdated else { return "Never" }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
}

private struct DetailRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack {
            Text(label)
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .fontWeight(.medium)
                .multilineTextAlignment(.trailing)
        }
        .font(.subheadline)
    }
}

private struct FallAlertCard: View {
    @ObservedObject var model: CareMateViewModel
    let fall: FallStatus

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top, spacing: 13) {
                ZStack {
                    Circle()
                        .fill(fallColor.opacity(0.14))
                        .frame(width: 48, height: 48)
                    Image(systemName: fallIcon)
                        .font(.system(size: 21, weight: .bold))
                        .foregroundStyle(fallColor)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text(fall.state.label)
                        .font(.headline)
                    Text("Updated \(fall.updatedAt.formatted(date: .omitted, time: .shortened))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }

            if let detail = fall.detail, !detail.isEmpty {
                Text(detail)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            if fall.state != .rejected {
                HStack(spacing: 10) {
                    if fall.state == .confirmed || fall.state == .uncertain {
                        Button {
                            Task { await model.acknowledgeFall() }
                        } label: {
                            HStack {
                                if model.isAcknowledging {
                                    ProgressView().tint(.white)
                                }
                                Text(model.isAcknowledging ? "Acknowledging…" : "Acknowledge")
                            }
                            .font(.headline)
                            .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(fallColor)
                        .controlSize(.large)
                        .disabled(model.isAcknowledging || model.isCancelling)
                    }

                    Button("Cancel") {
                        Task { await model.cancelFall() }
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                    .disabled(model.isAcknowledging || model.isCancelling)
                }
            }
        }
        .padding(18)
        .background(fallColor.opacity(0.075))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .stroke(fallColor.opacity(0.23))
        }
        .accessibilityElement(children: .contain)
    }

    private var fallColor: Color {
        switch fall.state {
        case .confirmed: .red
        case .possible, .uncertain: .orange
        case .rejected: .secondary
        }
    }

    private var fallIcon: String {
        switch fall.state {
        case .confirmed: "exclamationmark.triangle.fill"
        case .possible: "hourglass.circle.fill"
        case .uncertain: "questionmark.diamond.fill"
        case .rejected: "checkmark.circle.fill"
        }
    }
}

private struct ConnectionBadge: View {
    @ObservedObject var model: CareMateViewModel

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(color)
                .frame(width: 7, height: 7)
            Text(shortLabel)
                .font(.caption.weight(.semibold))
        }
        .foregroundStyle(color)
        .padding(.horizontal, 9)
        .padding(.vertical, 6)
        .background(color.opacity(0.1), in: Capsule())
        .accessibilityLabel("Hub connection: \(model.connectionState.label)")
    }

    private var shortLabel: String {
        switch model.connectionState {
        case .disconnected: "Offline"
        case .connecting: "Connecting"
        case .connected: model.isStale ? "Stale" : "Live"
        case .failed: "Issue"
        }
    }

    private var color: Color {
        switch model.connectionState {
        case .connected where !model.isStale: .green
        case .connecting: CareMateTheme.accent
        case .failed, .connected: .orange
        case .disconnected: .secondary
        }
    }
}

private struct InputField<Field: View>: View {
    let systemImage: String
    let field: Field

    init(systemImage: String, @ViewBuilder field: () -> Field) {
        self.systemImage = systemImage
        self.field = field()
    }

    var body: some View {
        HStack(spacing: 11) {
            Image(systemName: systemImage)
                .foregroundStyle(.secondary)
                .frame(width: 20)
            field
        }
        .padding(.horizontal, 13)
        .frame(minHeight: 48)
        .background(Color(uiColor: .tertiarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(Color.primary.opacity(0.06))
        }
    }
}

private struct CardIcon: View {
    let systemImage: String
    let color: Color

    var body: some View {
        Image(systemName: systemImage)
            .font(.system(size: 18, weight: .semibold))
            .foregroundStyle(color)
            .frame(width: 42, height: 42)
            .background(color.opacity(0.11), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

private struct CareCard<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(18)
            .background(Color(uiColor: .secondarySystemGroupedBackground))
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .stroke(Color.primary.opacity(0.055))
            }
    }
}

private struct PrivacyNotice: View {
    var body: some View {
        Label(
            "Camera frames are shown for live monitoring and request-scoped analysis; the app does not store them.",
            systemImage: "hand.raised.fill"
        )
        .font(.caption)
        .foregroundStyle(.secondary)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
    }
}

private struct PrototypeNotice: View {
    var body: some View {
        Label(
            "CareMate is a safety prototype, not a medical device or guaranteed emergency service.",
            systemImage: "info.circle.fill"
        )
        .font(.caption)
        .foregroundStyle(.secondary)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
    }
}
