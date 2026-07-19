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

    @Published var serverAddress = "http://caremate.local:8080"
    @Published var accessToken = ""
    @Published private(set) var connectionState = ConnectionState.disconnected
    @Published private(set) var status: HubStatus?
    @Published private(set) var activeFall: FallStatus?
    @Published private(set) var analysis: SpaceAnalysis?
    @Published private(set) var analysisSummary: AnalysisPresentationSummary?
    @Published private(set) var frameData: Data?
    @Published private(set) var lastUpdated: Date?
    @Published private(set) var isAnalyzing = false
    @Published private(set) var isGeneratingSummary = false
    @Published private(set) var isAcknowledging = false
    @Published private(set) var isCancelling = false

    private var client: (any CareMateAPI)?
    private var eventTask: Task<Void, Never>?
    private var frameTask: Task<Void, Never>?
    private var summaryTask: Task<Void, Never>?
    private let now: @Sendable () -> Date
    private let analysisSummarizer: any AnalysisSummarizing

    init(
        client: (any CareMateAPI)? = nil,
        analysisSummarizer: any AnalysisSummarizing = OnDeviceAnalysisSummarizer(),
        now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.client = client
        self.analysisSummarizer = analysisSummarizer
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
            client = try APIClient(baseURL: url, token: accessToken)
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
        var retryNanoseconds: UInt64 = 1_000_000_000
        while !Task.isCancelled {
            do {
                guard let client else { return }
                let stream = try await client.annotatedFrames()
                for try await frame in stream {
                    try Task.checkCancellation()
                    frameData = frame
                    retryNanoseconds = 1_000_000_000
                }
                throw APIClientError.streamEnded
            } catch is CancellationError {
                return
            } catch {
                // `/feed` is allowed to return 503 until Aryan wires the frame provider.
                // Preserve the last valid frame and retry without failing the event stream.
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
        let stream = try await client.annotatedFrames()
        for try await frame in stream {
            frameData = frame
            return
        }
        throw APIClientError.streamEnded
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
