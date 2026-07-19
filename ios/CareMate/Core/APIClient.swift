import Foundation
import OSLog

private let cameraFeedLogger = Logger(
    subsystem: "com.caremate.prototype",
    category: "CameraFeed"
)

private struct JPEGMarkerSummary {
    let hasSOI: Bool
    let hasEOI: Bool
    let hasDHT: Bool
    let hasDQT: Bool
    let hasSOF: Bool
    let hasSOS: Bool

    init(_ data: Data) {
        hasSOI = data.starts(with: [0xff, 0xd8])
        hasEOI = data.suffix(2).elementsEqual([0xff, 0xd9])
        hasDHT = data.range(of: Data([0xff, 0xc4])) != nil
        hasDQT = data.range(of: Data([0xff, 0xdb])) != nil
        hasSOF = data.range(of: Data([0xff, 0xc0])) != nil
            || data.range(of: Data([0xff, 0xc2])) != nil
        hasSOS = data.range(of: Data([0xff, 0xda])) != nil
    }
}

public enum APIClientError: LocalizedError, Sendable {
    case invalidConfiguration
    case invalidResponse
    case streamEnded
    case server(status: Int, message: String)

    public var errorDescription: String? {
        switch self {
        case .invalidConfiguration: "Enter a valid hub URL and access token."
        case .invalidResponse: "The hub returned an invalid response."
        case .streamEnded: "The hub closed the live connection."
        case let .server(_, message): message
        }
    }
}

public protocol CareMateAPI: Sendable {
    func status() async throws -> HubStatus
    func events() async throws -> AsyncThrowingStream<HubStreamMessage, Error>
    func analyzeSpace() async throws -> SpaceAnalysis
    func acknowledge() async throws -> AcceptedAction
    func cancel() async throws -> AcceptedAction
    func annotatedFrames() async throws -> AsyncThrowingStream<Data, Error>
    func frame() async throws -> Data
}

public actor APIClient: CareMateAPI {
    private static let maximumJPEGBytes = 10 * 1024 * 1024

    private let baseURL: URL
    private let token: String
    private let session: URLSession

    public init(baseURL: URL, token: String, session: URLSession = .shared) throws {
        guard !token.isEmpty,
              let scheme = baseURL.scheme?.lowercased(),
              scheme == "http" || scheme == "https"
        else {
            throw APIClientError.invalidConfiguration
        }
        self.baseURL = baseURL
        self.token = token
        self.session = session
    }

    public func status() async throws -> HubStatus {
        try await get("status", as: HubStatus.self, timeout: 6)
    }

    public func events() async throws -> AsyncThrowingStream<HubStreamMessage, Error> {
        var configuredRequest = request(url: endpoint("events"), timeout: 30)
        configuredRequest.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        let streamRequest = configuredRequest
        let session = session

        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let (bytes, response) = try await session.bytes(for: streamRequest)
                    try Self.validate(response)
                    let decoder = JSONDecoder()
                    for try await line in bytes.lines {
                        try Task.checkCancellation()
                        if line.hasPrefix(":") {
                            continuation.yield(.heartbeat)
                            continue
                        }
                        guard line.hasPrefix("data:") else { continue }
                        let payload = line.dropFirst(5).trimmingCharacters(in: .whitespaces)
                        guard !payload.isEmpty, let data = payload.data(using: .utf8) else { continue }
                        continuation.yield(.event(try decoder.decode(HubEvent.self, from: data)))
                    }
                    continuation.finish(throwing: APIClientError.streamEnded)
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    public func analyzeSpace() async throws -> SpaceAnalysis {
        try await post("analyze", as: SpaceAnalysis.self, timeout: 8)
    }

    public func acknowledge() async throws -> AcceptedAction {
        try await post("ack", as: AcceptedAction.self, timeout: 6)
    }

    public func cancel() async throws -> AcceptedAction {
        try await post("cancel", as: AcceptedAction.self, timeout: 6)
    }

    public func annotatedFrames() async throws -> AsyncThrowingStream<Data, Error> {
        var configuredRequest = request(url: endpoint("feed"), timeout: 30)
        configuredRequest.setValue("multipart/x-mixed-replace", forHTTPHeaderField: "Accept")
        let feedRequest = configuredRequest
        cameraFeedLogger.info("Opening authenticated MJPEG request path=/feed")
        return MJPEGStream.open(request: feedRequest, maximumJPEGBytes: Self.maximumJPEGBytes)
    }

    /// Fetch a single latest JPEG from `GET /frame`.
    ///
    /// This is a plain buffered request — the same path `status()` uses — so it
    /// works wherever status works. It is the reliable live-feed source: poll it
    /// on a timer for a smooth feed, without depending on `URLSession`'s flaky
    /// handling of `multipart/x-mixed-replace` MJPEG streams (the `annotatedFrames`
    /// path), which frequently delivers nothing through a proxy like ngrok.
    public func frame() async throws -> Data {
        var frameRequest = request(url: endpoint("frame"), timeout: 15)
        frameRequest.setValue("image/jpeg", forHTTPHeaderField: "Accept")
        cameraFeedLogger.info("Requesting authenticated single frame path=/frame")
        let (data, response) = try await session.data(for: frameRequest)
        let status = (response as? HTTPURLResponse)?.statusCode ?? -1
        let contentType = (response as? HTTPURLResponse)?
            .value(forHTTPHeaderField: "Content-Type") ?? "missing"
        let markers = JPEGMarkerSummary(data)
        cameraFeedLogger.info(
            "Single-frame response status=\(status) contentType=\(contentType, privacy: .public) bytes=\(data.count) SOI=\(markers.hasSOI) EOI=\(markers.hasEOI) DHT=\(markers.hasDHT) DQT=\(markers.hasDQT) SOF=\(markers.hasSOF) SOS=\(markers.hasSOS)"
        )
        try Self.validate(response, contentTypePrefix: "image/jpeg")
        guard !data.isEmpty else { throw APIClientError.invalidResponse }
        return data
    }

    private func get<T: Decodable>(
        _ path: String,
        as type: T.Type,
        timeout: TimeInterval
    ) async throws -> T {
        try await send(request(url: endpoint(path), timeout: timeout), as: type)
    }

    private func post<T: Decodable>(
        _ path: String,
        as type: T.Type,
        timeout: TimeInterval
    ) async throws -> T {
        var postRequest = request(url: endpoint(path), timeout: timeout)
        postRequest.httpMethod = "POST"
        return try await send(postRequest, as: type)
    }

    private func endpoint(_ path: String) -> URL {
        baseURL.appending(path: path)
    }

    private func request(url: URL, timeout: TimeInterval) -> URLRequest {
        Self.configuredRequest(url: url, token: token, timeout: timeout)
    }

    static func configuredRequest(url: URL, token: String, timeout: TimeInterval) -> URLRequest {
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        // Required by ngrok's free tunnel. Harmless when talking directly to
        // the hub or through a tunnel that does not use an interstitial.
        request.setValue("true", forHTTPHeaderField: "ngrok-skip-browser-warning")
        request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        return request
    }

    private func send<T: Decodable>(_ request: URLRequest, as type: T.Type) async throws -> T {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIClientError.invalidResponse
        }
        guard (200 ..< 300).contains(http.statusCode) else {
            throw Self.decodeServerError(data: data, status: http.statusCode)
        }
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            throw APIClientError.invalidResponse
        }
    }

    private static func validate(
        _ response: URLResponse,
        contentTypePrefix: String? = nil
    ) throws {
        guard let http = response as? HTTPURLResponse else {
            throw APIClientError.invalidResponse
        }
        guard (200 ..< 300).contains(http.statusCode) else {
            throw APIClientError.server(
                status: http.statusCode,
                message: "The hub returned HTTP \(http.statusCode)."
            )
        }
        if let contentTypePrefix,
           http.value(forHTTPHeaderField: "Content-Type")?.hasPrefix(contentTypePrefix) != true {
            throw APIClientError.invalidResponse
        }
    }

    private static func decodeServerError(data: Data, status: Int) -> APIClientError {
        let message = (try? JSONDecoder().decode(HubErrorEnvelope.self, from: data))?.error
            ?? "The hub returned HTTP \(status)."
        return .server(status: status, message: message)
    }
}

struct MJPEGFrameParser: Sendable {
    private static let startMarker = Data([0xff, 0xd8])
    private static let endMarker = Data([0xff, 0xd9])

    private var buffer = Data()
    private let maximumJPEGBytes: Int

    init(maximumJPEGBytes: Int = 10 * 1024 * 1024) {
        self.maximumJPEGBytes = maximumJPEGBytes
    }

    mutating func append(_ data: Data) -> [Data] {
        buffer.append(data)
        var frames: [Data] = []

        while let start = buffer.range(of: Self.startMarker)?.lowerBound {
            if start > buffer.startIndex {
                buffer.removeSubrange(buffer.startIndex ..< start)
            }
            guard buffer.count <= maximumJPEGBytes else {
                buffer.removeAll(keepingCapacity: true)
                return frames
            }
            guard let end = buffer.range(
                of: Self.endMarker,
                options: [],
                in: buffer.index(buffer.startIndex, offsetBy: 2) ..< buffer.endIndex
            ) else {
                return frames
            }

            let frameEnd = end.upperBound
            frames.append(Data(buffer[buffer.startIndex ..< frameEnd]))
            buffer.removeSubrange(buffer.startIndex ..< frameEnd)
        }

        // Keep a trailing 0xff because the JPEG start marker may be split
        // between URLSession data callbacks; discard unrelated multipart text.
        if buffer.count > 1 {
            buffer = buffer.last == 0xff ? Data([0xff]) : Data()
        }
        return frames
    }
}

private enum MJPEGStream {
    static func open(
        request: URLRequest,
        maximumJPEGBytes: Int
    ) -> AsyncThrowingStream<Data, Error> {
        AsyncThrowingStream { continuation in
            let delegate = MJPEGStreamDelegate(
                continuation: continuation,
                maximumJPEGBytes: maximumJPEGBytes
            )
            let queue = OperationQueue()
            queue.maxConcurrentOperationCount = 1
            let session = URLSession(
                configuration: .ephemeral,
                delegate: delegate,
                delegateQueue: queue
            )
            let task = session.dataTask(with: request)
            continuation.onTermination = { _ in
                task.cancel()
                session.invalidateAndCancel()
            }
            task.resume()
        }
    }
}

private final class MJPEGStreamDelegate: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private let continuation: AsyncThrowingStream<Data, Error>.Continuation
    private var parser: MJPEGFrameParser
    private var responseAccepted = false
    private var receivedBytes = 0
    private var receivedChunks = 0
    private var emittedFrames = 0

    init(
        continuation: AsyncThrowingStream<Data, Error>.Continuation,
        maximumJPEGBytes: Int
    ) {
        self.continuation = continuation
        parser = MJPEGFrameParser(maximumJPEGBytes: maximumJPEGBytes)
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
    ) {
        guard let http = response as? HTTPURLResponse else {
            cameraFeedLogger.error("MJPEG response was not HTTP")
            continuation.finish(throwing: APIClientError.invalidResponse)
            completionHandler(.cancel)
            return
        }
        let contentType = http.value(forHTTPHeaderField: "Content-Type") ?? "missing"
        cameraFeedLogger.info(
            "MJPEG response status=\(http.statusCode) contentType=\(contentType, privacy: .public)"
        )
        guard (200 ..< 300).contains(http.statusCode) else {
            continuation.finish(throwing: APIClientError.server(
                status: http.statusCode,
                message: "The hub returned HTTP \(http.statusCode) for the camera feed."
            ))
            completionHandler(.cancel)
            return
        }
        let normalizedContentType = contentType.lowercased()
        // URLSession may expose the outer MJPEG response as multipart or
        // decompose it and deliver each replacement part as image/jpeg.
        guard normalizedContentType.hasPrefix("multipart/x-mixed-replace")
                || normalizedContentType.hasPrefix("image/jpeg")
        else {
            continuation.finish(throwing: APIClientError.server(
                status: http.statusCode,
                message: "The camera feed returned an unexpected content type: \(contentType)."
            ))
            completionHandler(.cancel)
            return
        }
        responseAccepted = true
        cameraFeedLogger.info("MJPEG response accepted; waiting for JPEG bytes")
        completionHandler(.allow)
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive data: Data
    ) {
        guard responseAccepted else { return }
        receivedChunks += 1
        receivedBytes += data.count
        let frames = parser.append(data)
        if receivedChunks <= 3 {
            cameraFeedLogger.debug(
                "MJPEG data callback chunk=\(self.receivedChunks) chunkBytes=\(data.count) totalBytes=\(self.receivedBytes) parsedFrames=\(frames.count)"
            )
        }
        for frame in frames {
            emittedFrames += 1
            if emittedFrames == 1 || emittedFrames.isMultiple(of: 100) {
                let markers = JPEGMarkerSummary(frame)
                cameraFeedLogger.info(
                    "MJPEG parser emitted frame=\(self.emittedFrames) bytes=\(frame.count) totalStreamBytes=\(self.receivedBytes) SOI=\(markers.hasSOI) EOI=\(markers.hasEOI) DHT=\(markers.hasDHT) DQT=\(markers.hasDQT) SOF=\(markers.hasSOF) SOS=\(markers.hasSOS)"
                )
            }
            continuation.yield(frame)
        }
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: Error?
    ) {
        if let error {
            cameraFeedLogger.error(
                "MJPEG request completed with error=\(error.localizedDescription, privacy: .public) chunks=\(self.receivedChunks) bytes=\(self.receivedBytes) frames=\(self.emittedFrames)"
            )
            continuation.finish(throwing: error)
        } else {
            cameraFeedLogger.error(
                "MJPEG request ended without transport error chunks=\(self.receivedChunks) bytes=\(self.receivedBytes) frames=\(self.emittedFrames)"
            )
            continuation.finish(throwing: APIClientError.streamEnded)
        }
        session.finishTasksAndInvalidate()
    }
}
