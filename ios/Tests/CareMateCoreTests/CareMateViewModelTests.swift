import Foundation
import XCTest
@testable import CareMateAppLogic
@testable import CareMateCore

private enum FakeError: LocalizedError, Sendable {
    case network
    var errorDescription: String? { "Network unavailable" }
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

    private static func decode<T: Decodable>(_ string: String) -> T {
        try! JSONDecoder().decode(T.self, from: Data(string.utf8))
    }
}

@MainActor
final class CareMateViewModelTests: XCTestCase {
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
        let model = CareMateViewModel(client: FakeAPI())
        await model.analyzeSpace()

        XCTAssertEqual(model.analysis?.requestID, "req-1")
        XCTAssertEqual(model.currentActivity, .standing)
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
