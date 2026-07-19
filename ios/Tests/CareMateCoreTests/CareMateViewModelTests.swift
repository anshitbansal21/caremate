import Foundation
import XCTest
@testable import CareMateAppLogic
@testable import CareMateCore

private enum FakeError: LocalizedError, Sendable {
    case network
    var errorDescription: String? { "Network unavailable" }
}

private struct FakeSummarizer: AnalysisSummarizing {
    func summarize(_ analysis: SpaceAnalysis) async -> AnalysisPresentationSummary {
        AnalysisPresentationSummary(
            paragraph: "The person is standing near the bed, with no visible risks reported.",
            source: .foundationModel
        )
    }
}

private actor FakeAPI: CareMateAPI {
    private var failStatus = false
    private let currentStatus: HubStatus
    private let streamEvents: [HubEvent]
    private var frames: [Result<Data, FakeError>]
    private let analysisResult: SpaceAnalysis
    private(set) var acknowledgements = 0
    private(set) var cancellations = 0

    init(
        status: HubStatus = Fixtures.readyStatus,
        events: [HubEvent] = [],
        frames: [Result<Data, FakeError>] = [],
        analysis: SpaceAnalysis = Fixtures.analysis
    ) {
        currentStatus = status
        streamEvents = events
        self.frames = frames
        analysisResult = analysis
    }

    func setFailStatus(_ value: Bool) { failStatus = value }

    func status() async throws -> HubStatus {
        if failStatus { throw FakeError.network }
        return currentStatus
    }

    func events() async throws -> AsyncThrowingStream<HubStreamMessage, Error> {
        let events = streamEvents
        return AsyncThrowingStream { continuation in
            events.forEach { continuation.yield(.event($0)) }
            continuation.finish()
        }
    }

    func analyzeSpace() async throws -> SpaceAnalysis { analysisResult }

    func acknowledge() async throws -> AcceptedAction {
        acknowledgements += 1
        return AcceptedAction(accepted: "ack")
    }

    func cancel() async throws -> AcceptedAction {
        cancellations += 1
        return AcceptedAction(accepted: "cancel")
    }

    func annotatedFrames() async throws -> AsyncThrowingStream<Data, Error> {
        guard !frames.isEmpty else { throw FakeError.network }
        let result = frames.removeFirst()
        return AsyncThrowingStream { continuation in
            do {
                continuation.yield(try result.get())
                continuation.finish()
            } catch {
                continuation.finish(throwing: error)
            }
        }
    }

    func frame() async throws -> Data {
        guard !frames.isEmpty else { throw FakeError.network }
        return try frames.removeFirst().get()
    }

    func actionCounts() -> (Int, Int) { (acknowledgements, cancellations) }
}

private final class TestClock: @unchecked Sendable {
    private let lock = NSLock()
    private var value = Date(timeIntervalSince1970: 1_000)

    func now() -> Date {
        lock.lock()
        defer { lock.unlock() }
        return value
    }

    func advance(seconds: TimeInterval) {
        lock.lock()
        value = value.addingTimeInterval(seconds)
        lock.unlock()
    }
}

private final class FakeConnectionSettingsStore: ConnectionSettingsStoring {
    private(set) var settings: ConnectionSettings
    private(set) var savedSettings: ConnectionSettings?

    init(settings: ConnectionSettings) {
        self.settings = settings
    }

    func load() -> ConnectionSettings { settings }

    func save(_ settings: ConnectionSettings) {
        self.settings = settings
        savedSettings = settings
    }
}

private final class FakeCredentialStore: CredentialStoring {
    var token: String?

    func loadToken() -> String? { token }
    func saveToken(_ token: String) { self.token = token }
}

private enum Fixtures {
    static let readyStatus = HubStatus(state: .ready, level: .none, timestampMilliseconds: 100)

    static let analysis: SpaceAnalysis = decode(#"""
    {"request_id":"req-1","person_state":"standing","room_summary":"Person standing near the bed.","risk_observations":[],"alert_recommendation":"none","uncertain":false,"captured_at":""}
    """#)

    static let possibleEvent: HubEvent = decode(#"""
    {"type":"status","state":"awaiting_vision","level":"possible","ts":200}
    """#)

    static let confirmedEvent: HubEvent = decode(#"""
    {"type":"alert","state":"alerting","level":"confirmed","detail":"vision confirmed","ts":300}
    """#)

    fileprivate static func decode<T: Decodable>(_ string: String) -> T {
        try! JSONDecoder().decode(T.self, from: Data(string.utf8))
    }
}

@MainActor
final class CareMateViewModelTests: XCTestCase {
    func testConnectionSettingsStorePersistsURLAndDelegatesTokenToSecureStore() throws {
        let suiteName = "CareMateViewModelTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        let credentialStore = FakeCredentialStore()
        let store = ConnectionSettingsStore(
            defaults: defaults,
            credentialStore: credentialStore
        )
        let settings = ConnectionSettings(
            serverAddress: "https://caremate.example.test",
            accessToken: "saved-token"
        )
        defer { defaults.removePersistentDomain(forName: suiteName) }

        try store.save(settings)

        XCTAssertEqual(store.load(), settings)
        XCTAssertEqual(credentialStore.token, "saved-token")
    }

    func testRestoresSavedConnectionSettingsOnRelaunch() {
        let settings = ConnectionSettings(
            serverAddress: "https://caremate.example.test",
            accessToken: "saved-token"
        )
        let model = CareMateViewModel(
            client: FakeAPI(),
            connectionSettingsStore: FakeConnectionSettingsStore(settings: settings)
        )

        XCTAssertEqual(model.serverAddress, settings.serverAddress)
        XCTAssertEqual(model.accessToken, settings.accessToken)
    }

    func testConnectPersistsValidatedConnectionSettings() {
        let store = FakeConnectionSettingsStore(
            settings: ConnectionSettings(serverAddress: "", accessToken: "")
        )
        let model = CareMateViewModel(connectionSettingsStore: store)
        model.serverAddress = "https://caremate.example.test"
        model.accessToken = "new-token"

        model.connect()
        model.disconnect()

        XCTAssertEqual(
            store.savedSettings,
            ConnectionSettings(
                serverAddress: "https://caremate.example.test",
                accessToken: "new-token"
            )
        )
    }

    func testStatusBecomesStaleAfterThirtySeconds() async throws {
        let clock = TestClock()
        let model = CareMateViewModel(client: FakeAPI(), now: clock.now)

        try await model.refreshStatusOnce()
        XCTAssertFalse(model.isStale)
        clock.advance(seconds: 31)
        XCTAssertTrue(model.isStale)
    }

    func testNetworkLossPreservesLastKnownStatusAndShowsFailure() async throws {
        let api = FakeAPI()
        let model = CareMateViewModel(client: api)
        try await model.refreshStatusOnce()
        await api.setFailStatus(true)

        do {
            try await model.refreshStatusOnce()
            XCTFail("Expected network failure")
        } catch {}

        XCTAssertEqual(model.status?.state, .ready)
        if case .failed = model.connectionState {} else {
            XCTFail("Expected visible connection failure")
        }
    }

    func testCameraFrameRecoversAfterFailure() async throws {
        let jpeg = Data([0xff, 0xd8, 0xff, 0xd9])
        let api = FakeAPI(frames: [.failure(.network), .success(jpeg)])
        let model = CareMateViewModel(client: api)

        do {
            try await model.refreshFrameOnce()
            XCTFail("Expected first frame to fail")
        } catch {}
        try await model.refreshFrameOnce()

        XCTAssertEqual(model.frameData, jpeg)
    }

    func testLoadSingleFramePublishesFallbackImage() async {
        let jpeg = Data([0xff, 0xd8, 0x01, 0xff, 0xd9])
        let model = CareMateViewModel(client: FakeAPI(frames: [.success(jpeg)]))

        await model.loadSingleFrame()

        XCTAssertEqual(model.frameData, jpeg)
        XCTAssertNil(model.feedError)
        XCTAssertFalse(model.isLoadingSingleFrame)
    }

    func testForegroundAndBackgroundStartAndStopMonitoring() {
        let model = CareMateViewModel(client: FakeAPI())
        model.setForeground(true)
        XCTAssertTrue(model.isMonitoring)
        model.setForeground(false)
        XCTAssertFalse(model.isMonitoring)
    }

    func testPossibleAndConfirmedEventsRemainDistinct() {
        let model = CareMateViewModel(client: FakeAPI())
        model.apply(Fixtures.possibleEvent)
        XCTAssertEqual(model.activeFall?.state, .possible)

        model.apply(Fixtures.confirmedEvent)
        XCTAssertEqual(model.activeFall?.state, .confirmed)
        XCTAssertEqual(model.activeFall?.detail, "vision confirmed")
    }

    func testSSEHeartbeatRefreshesConnectionFreshness() throws {
        let clock = TestClock()
        let model = CareMateViewModel(client: FakeAPI(), now: clock.now)
        model.apply(Fixtures.possibleEvent)
        clock.advance(seconds: 31)
        XCTAssertTrue(model.isStale)

        model.apply(.heartbeat)
        XCTAssertFalse(model.isStale)
    }

    func testAnalyzeUsesHubResultAsCurrentActivity() async {
        let model = CareMateViewModel(client: FakeAPI(), analysisSummarizer: FakeSummarizer())
        await model.analyzeSpace()
        while model.isGeneratingSummary { await Task.yield() }

        XCTAssertEqual(model.analysis?.requestID, "req-1")
        XCTAssertEqual(model.currentActivity, .standing)
        XCTAssertEqual(
            model.analysisSummary?.paragraph,
            "The person is standing near the bed, with no visible risks reported."
        )
        XCTAssertEqual(model.analysisSummary?.source, .foundationModel)
    }

    func testDeterministicSummaryPreservesUncertaintyWhenModelIsUnavailable() {
        let uncertain: SpaceAnalysis = Fixtures.decode(#"""
        {"request_id":"req-2","person_state":"uncertain","room_summary":"Person not clearly visible.","risk_observations":[],"alert_recommendation":"check","uncertain":true,"captured_at":""}
        """#)

        let summary = OnDeviceAnalysisSummarizer.fallbackSummary(for: uncertain)

        XCTAssertEqual(summary.source, .deterministicFallback)
        XCTAssertTrue(summary.paragraph.contains("uncertain"))
        XCTAssertTrue(summary.paragraph.contains("should be checked"))
    }

    func testAcknowledgeAndCancelUseAryansGlobalActionRoutes() async {
        let api = FakeAPI()
        let model = CareMateViewModel(client: api)

        await model.acknowledgeFall()
        await model.cancelFall()

        let counts = await api.actionCounts()
        XCTAssertEqual(counts.0, 1)
        XCTAssertEqual(counts.1, 1)
    }
}
