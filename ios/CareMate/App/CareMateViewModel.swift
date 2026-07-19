import Foundation
import Combine
#if SWIFT_PACKAGE
import CareMateCore
#endif

@MainActor
final class CareMateViewModel: ObservableObject {
    enum ConnectionState: Equatable {
        case disconnected
        case connecting
        case connected
        case failed(String)

        var label: String {
            switch self {
            case .disconnected: "Disconnected"
            case .connecting: "Connecting…"
            case .connected: "Connected"
            case .failed: "Connection problem"
            }
        }
    }

    @Published var serverAddress: String
    @Published var accessToken: String
    @Published private(set) var connectionState = ConnectionState.disconnected
    @Published private(set) var status: HubStatus?
    @Published private(set) var activeFall: FallStatus?
    @Published private(set) var analysis: SpaceAnalysis?
    @Published private(set) var analysisSummary: AnalysisPresentationSummary?
    @Published private(set) var frameData: Data?
    @Published private(set) var feedError: String?
    @Published private(set) var lastUpdated: Date?
    @Published private(set) var isAnalyzing = false
    @Published private(set) var isLoadingSingleFrame = false
    @Published private(set) var isGeneratingSummary = false
    @Published private(set) var isAcknowledging = false
    @Published private(set) var isCancelling = false

    private var client: (any CareMateAPI)?
    private var eventTask: Task<Void, Never>?
    private var frameTask: Task<Void, Never>?
    private var summaryTask: Task<Void, Never>?
    private let now: @Sendable () -> Date
    private let analysisSummarizer: any AnalysisSummarizing
    private let connectionSettingsStore: any ConnectionSettingsStoring

    init(
        client: (any CareMateAPI)? = nil,
        analysisSummarizer: any AnalysisSummarizing = OnDeviceAnalysisSummarizer(),
        connectionSettingsStore: any ConnectionSettingsStoring = ConnectionSettingsStore(),
        now: @escaping @Sendable () -> Date = { Date() }
    ) {
        let settings = connectionSettingsStore.load()
        serverAddress = settings.serverAddress
        accessToken = settings.accessToken
        self.client = client
        self.analysisSummarizer = analysisSummarizer
        self.connectionSettingsStore = connectionSettingsStore
        self.now = now
    }

    var isStale: Bool {
        guard let lastUpdated else { return true }
        return now().timeIntervalSince(lastUpdated) > 30
    }

    var isMonitoring: Bool { eventTask != nil && frameTask != nil }
    var currentActivity: PersonState { analysis?.personState ?? .uncertain }

    func connect() {
        disconnect(clearData: true)
        guard let url = URL(string: serverAddress) else {
            connectionState = .failed("Enter a valid hub URL.")
            return
        }
        do {
            let configuredClient = try APIClient(baseURL: url, token: accessToken)
            try connectionSettingsStore.save(
                ConnectionSettings(serverAddress: serverAddress, accessToken: accessToken)
            )
            client = configuredClient
        } catch {
            connectionState = .failed(error.localizedDescription)
            return
        }
        connectionState = .connecting
        startLoops()
    }

    func disconnect(clearData: Bool = false) {
        eventTask?.cancel()
        frameTask?.cancel()
        summaryTask?.cancel()
        eventTask = nil
        frameTask = nil
        summaryTask = nil
        client = nil
        connectionState = .disconnected
        if clearData {
            status = nil
            activeFall = nil
            analysis = nil
            analysisSummary = nil
            frameData = nil
            feedError = nil
            lastUpdated = nil
            isGeneratingSummary = false
        }
    }

    func setForeground(_ foreground: Bool) {
        if foreground {
            if client != nil, eventTask == nil { startLoops() }
        } else {
            eventTask?.cancel()
            frameTask?.cancel()
            eventTask = nil
            frameTask = nil
        }
    }

    func analyzeSpace() async {
        guard let client, !isAnalyzing else { return }
        isAnalyzing = true
        defer { isAnalyzing = false }
        do {
            receiveAnalysis(try await client.analyzeSpace())
        } catch {
            connectionState = .failed(error.localizedDescription)
        }
    }

    func loadSingleFrame() async {
        guard client != nil, !isLoadingSingleFrame else { return }
        isLoadingSingleFrame = true
        defer { isLoadingSingleFrame = false }
        do {
            try await refreshFrameOnce()
            feedError = nil
        } catch {
            feedError = error.localizedDescription
        }
    }

    func acknowledgeFall() async {
        guard let client, !isAcknowledging else { return }
        isAcknowledging = true
        defer { isAcknowledging = false }
        do {
            let result = try await client.acknowledge()
            guard result.accepted == "ack" else { throw APIClientError.invalidResponse }
            lastUpdated = now()
        } catch {
            connectionState = .failed(error.localizedDescription)
        }
    }

    func cancelFall() async {
        guard let client, !isCancelling else { return }
        isCancelling = true
        defer { isCancelling = false }
        do {
            let result = try await client.cancel()
            guard result.accepted == "cancel" else { throw APIClientError.invalidResponse }
            lastUpdated = now()
        } catch {
            connectionState = .failed(error.localizedDescription)
        }
    }

    private func startLoops() {
        guard client != nil else { return }
        eventTask = Task { [weak self] in await self?.runEventLoop() }
        frameTask = Task { [weak self] in await self?.runFrameLoop() }
    }

    private func runEventLoop() async {
        var retryNanoseconds: UInt64 = 500_000_000
        while !Task.isCancelled {
            do {
                try await refreshStatusOnce()
                guard let client else { return }
                let stream = try await client.events()
                for try await message in stream {
                    try Task.checkCancellation()
                    apply(message)
                    connectionState = .connected
                    retryNanoseconds = 500_000_000
                }
                throw APIClientError.streamEnded
            } catch is CancellationError {
                return
            } catch {
                connectionState = .failed(error.localizedDescription)
                try? await Task.sleep(nanoseconds: retryNanoseconds)
                retryNanoseconds = min(retryNanoseconds * 2, 8_000_000_000)
            }
        }
    }

    private func runFrameLoop() async {
        // Poll GET /frame on a timer rather than consuming the MJPEG /feed stream.
        // /frame is a plain buffered request (the same path status uses), so it is
        // reliable through a proxy; multipart/x-mixed-replace over URLSession is not.
        var retryNanoseconds: UInt64 = 1_000_000_000
        let pollIntervalNanoseconds: UInt64 = 150_000_000  // ~6-7 fps: smooth, light
        while !Task.isCancelled {
            do {
                guard let client else { return }
                let frame = try await client.frame()
                try Task.checkCancellation()
                frameData = frame
                feedError = nil
                retryNanoseconds = 1_000_000_000
                try await Task.sleep(nanoseconds: pollIntervalNanoseconds)
            } catch is CancellationError {
                return
            } catch {
                // Preserve the last frame and expose the failure while retrying.
                feedError = error.localizedDescription
                try? await Task.sleep(nanoseconds: retryNanoseconds)
                retryNanoseconds = min(retryNanoseconds * 2, 8_000_000_000)
            }
        }
    }

    func refreshStatusOnce() async throws {
        guard let client else { throw APIClientError.invalidConfiguration }
        do {
            apply(try await client.status())
            connectionState = .connected
        } catch {
            connectionState = .failed(error.localizedDescription)
            throw error
        }
    }

    func refreshFrameOnce() async throws {
        guard let client else { throw APIClientError.invalidConfiguration }
        frameData = try await client.frame()
        feedError = nil
    }

    func apply(_ event: HubEvent) {
        if let eventStatus = event.status {
            apply(eventStatus, detail: event.detail)
        }
        if let eventAnalysis = event.analysis {
            receiveAnalysis(eventAnalysis)
        }
    }

    func apply(_ message: HubStreamMessage) {
        switch message {
        case let .event(event): apply(event)
        case .heartbeat: lastUpdated = now()
        }
    }

    private func apply(_ newStatus: HubStatus, detail: String? = nil) {
        status = newStatus
        lastUpdated = now()
        if let fallState = newStatus.fallState {
            activeFall = FallStatus(state: fallState, updatedAt: now(), detail: detail)
        } else {
            activeFall = nil
        }
    }

    private func receiveAnalysis(_ newAnalysis: SpaceAnalysis) {
        let isSameRequest = analysis?.requestID == newAnalysis.requestID
        analysis = newAnalysis
        lastUpdated = now()

        if isSameRequest, analysisSummary != nil || isGeneratingSummary {
            return
        }

        summaryTask?.cancel()
        analysisSummary = nil
        isGeneratingSummary = true
        let summarizer = analysisSummarizer
        let requestID = newAnalysis.requestID
        summaryTask = Task { [weak self] in
            let result = await summarizer.summarize(newAnalysis)
            guard !Task.isCancelled, let self, self.analysis?.requestID == requestID else { return }
            self.analysisSummary = result
            self.isGeneratingSummary = false
            self.summaryTask = nil
        }
    }
}
