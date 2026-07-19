import Foundation

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
        return MJPEGStream.open(request: feedRequest, maximumJPEGBytes: Self.maximumJPEGBytes)
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
            continuation.finish(throwing: APIClientError.invalidResponse)
            completionHandler(.cancel)
            return
        }
        guard (200 ..< 300).contains(http.statusCode) else {
            continuation.finish(throwing: APIClientError.server(
                status: http.statusCode,
                message: "The hub returned HTTP \(http.statusCode) for the camera feed."
            ))
            completionHandler(.cancel)
            return
        }
        let contentType = http.value(forHTTPHeaderField: "Content-Type") ?? "missing"
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
        completionHandler(.allow)
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive data: Data
    ) {
        guard responseAccepted else { return }
        for frame in parser.append(data) {
            continuation.yield(frame)
        }
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: Error?
    ) {
        if let error {
            continuation.finish(throwing: error)
        } else {
            continuation.finish(throwing: APIClientError.streamEnded)
        }
        session.finishTasksAndInvalidate()
    }
}
