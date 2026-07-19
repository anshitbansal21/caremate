import Foundation
import XCTest
@testable import CareMateAppLogic
@testable import CareMateCore

private enum LiveTestError: Error {
    case timedOut
    case streamEnded
}

final class LiveAPIIntegrationTests: XCTestCase {
    func testConfiguredLiveFeedProducesJPEG() async throws {
        let environment = ProcessInfo.processInfo.environment
        guard let address = environment["CAREMATE_LIVE_URL"],
              let url = URL(string: address),
              let token = environment["CAREMATE_LIVE_TOKEN"]
        else {
            throw XCTSkip("Set CAREMATE_LIVE_URL and CAREMATE_LIVE_TOKEN to run the live feed test.")
        }

        let client = try APIClient(baseURL: url, token: token)
        let status: HubStatus
        do {
            status = try await client.status()
        } catch {
            let nsError = error as NSError
            XCTFail("Status request failed: \(nsError), userInfo: \(nsError.userInfo)")
            throw error
        }
        XCTAssertFalse(status.state.rawValue.isEmpty)

        let stream: AsyncThrowingStream<Data, Error>
        do {
            stream = try await client.annotatedFrames()
        } catch {
            let nsError = error as NSError
            XCTFail("Feed setup failed: \(nsError), userInfo: \(nsError.userInfo)")
            throw error
        }
        let frame: Data
        do {
            frame = try await firstFrame(from: stream)
        } catch {
            let nsError = error as NSError
            XCTFail("Feed streaming failed: \(nsError), userInfo: \(nsError.userInfo)")
            throw error
        }
        XCTAssertGreaterThan(frame.count, 4)
        XCTAssertEqual(Array(frame.prefix(2)), [0xff, 0xd8])
        XCTAssertEqual(Array(frame.suffix(2)), [0xff, 0xd9])
    }

    @MainActor
    func testConfiguredLiveViewModelPublishesStatusAndFrame() async throws {
        let environment = ProcessInfo.processInfo.environment
        guard let address = environment["CAREMATE_LIVE_URL"],
              let url = URL(string: address),
              let token = environment["CAREMATE_LIVE_TOKEN"]
        else {
            throw XCTSkip("Set CAREMATE_LIVE_URL and CAREMATE_LIVE_TOKEN to run the live app test.")
        }

        let client = try APIClient(baseURL: url, token: token)
        let model = CareMateViewModel(client: client)
        model.setForeground(true)

        let deadline = ContinuousClock.now + .seconds(15)
        while (model.status == nil || model.frameData == nil), ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(100))
        }

        XCTAssertNotNil(model.status)
        XCTAssertNotNil(model.frameData)
        XCTAssertNil(model.feedError)
        model.disconnect(clearData: true)
    }

    private func firstFrame(
        from stream: AsyncThrowingStream<Data, Error>
    ) async throws -> Data {
        try await withThrowingTaskGroup(of: Data.self) { group in
            group.addTask {
                for try await frame in stream {
                    return frame
                }
                throw LiveTestError.streamEnded
            }
            group.addTask {
                try await Task.sleep(for: .seconds(15))
                throw LiveTestError.timedOut
            }
            guard let result = try await group.next() else {
                throw LiveTestError.streamEnded
            }
            group.cancelAll()
            return result
        }
    }
}
