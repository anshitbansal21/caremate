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
        let session = session

        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let (bytes, response) = try await session.bytes(for: feedRequest)
                    try Self.validate(response, contentTypePrefix: "multipart/x-mixed-replace")

                    var previous: UInt8?
                    var frame = Data()
                    var capturing = false

                    for try await byte in bytes {
                        try Task.checkCancellation()
                        if !capturing {
                            if previous == 0xff, byte == 0xd8 {
                                frame = Data([0xff, 0xd8])
                                capturing = true
                                previous = nil
                            } else {
                                previous = byte
                            }
                            continue
                        }

                        frame.append(byte)
                        if frame.count > Self.maximumJPEGBytes {
                            frame.removeAll(keepingCapacity: false)
                            capturing = false
                            previous = nil
                            continue
                        }
                        if previous == 0xff, byte == 0xd9 {
                            continuation.yield(frame)
                            frame.removeAll(keepingCapacity: true)
                            capturing = false
                            previous = nil
                        } else {
                            previous = byte
                        }
                    }
                    continuation.finish(throwing: APIClientError.streamEnded)
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
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
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
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
