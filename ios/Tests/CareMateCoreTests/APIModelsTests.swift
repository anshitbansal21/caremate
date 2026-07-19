import XCTest
@testable import CareMateCore

final class APIModelsTests: XCTestCase {
    private let decoder = JSONDecoder()

    func testStatusDecodesAryansSnapshotContract() throws {
        let status = try decoder.decode(HubStatus.self, from: Data(#"""
        {"state":"awaiting_vision","level":"possible","ts":123456}
        """#.utf8))

        XCTAssertEqual(status.state, .awaitingVision)
        XCTAssertEqual(status.level, .possible)
        XCTAssertEqual(status.fallState, .possible)
        XCTAssertNotEqual(status.fallState, .confirmed)
    }

    func testAlertSSEEventPreservesDetail() throws {
        let event = try decodeEvent(#"""
        {"type":"alert","state":"alerting","level":"confirmed","detail":"vision: lying + sustained no-motion","ts":123999}
        """#)

        XCTAssertEqual(event.type, .alert)
        XCTAssertEqual(event.status?.fallState, .confirmed)
        XCTAssertEqual(event.detail, "vision: lying + sustained no-motion")
    }

    func testAnalysisEventAllowsUnavailableCaptureTimestamp() throws {
        let event = try decodeEvent(#"""
        {"type":"analysis","request_id":"req-ab12","person_state":"on_bed","room_summary":"Person resting on the bed.","risk_observations":[],"alert_recommendation":"none","uncertain":false,"captured_at":"","ts":124500}
        """#)

        XCTAssertEqual(event.analysis?.requestID, "req-ab12")
        XCTAssertEqual(event.analysis?.personState, .onBed)
        XCTAssertNil(event.analysis?.capturedAtDate)
    }

    func testRequestsIncludeHubAuthAndNgrokBypassHeaders() throws {
        let request = APIClient.configuredRequest(
            url: try XCTUnwrap(URL(string: "https://example.ngrok-free.app/feed")),
            token: "test-token",
            timeout: 30
        )

        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer test-token")
        XCTAssertEqual(request.value(forHTTPHeaderField: "ngrok-skip-browser-warning"), "true")
    }

    func testMJPEGParserHandlesMarkersSplitAcrossNetworkChunks() {
        var parser = MJPEGFrameParser(maximumJPEGBytes: 100)

        XCTAssertTrue(parser.append(Data([0x2d, 0x2d, 0x66, 0x72, 0x61, 0x6d, 0x65,
                                          0x0d, 0x0a, 0xff])).isEmpty)
        let frames = parser.append(Data([0xd8, 0x01, 0x02, 0xff, 0xd9,
                                         0x2d, 0x2d, 0x66, 0x72, 0x61, 0x6d, 0x65,
                                         0xff, 0xd8, 0x03, 0xff, 0xd9]))

        XCTAssertEqual(frames, [
            Data([0xff, 0xd8, 0x01, 0x02, 0xff, 0xd9]),
            Data([0xff, 0xd8, 0x03, 0xff, 0xd9])
        ])
    }

    private func decodeEvent(_ json: String) throws -> HubEvent {
        try decoder.decode(HubEvent.self, from: Data(json.utf8))
    }
}
