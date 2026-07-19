import Foundation

public enum HubState: String, Codable, Sendable {
    case ready
    case awaitingVision = "awaiting_vision"
    case confirmedFall = "confirmed_fall"
    case alerting
    case uncertain
    case rejected
    case fault

    public var label: String {
        switch self {
        case .ready: "Ready"
        case .awaitingVision: "Checking possible fall"
        case .confirmedFall: "Fall confirmed"
        case .alerting: "Alerting"
        case .uncertain: "Uncertain—check user"
        case .rejected: "Fall not confirmed"
        case .fault: "Hub fault"
        }
    }
}

public enum AlertLevel: String, Codable, Sendable {
    case none
    case possible
    case check
    case confirmed
}

public enum PersonState: String, Codable, Sendable {
    case onBed = "on_bed"
    case standing
    case sitting
    case lying
    case walking
    case notVisible = "not_visible"
    case uncertain

    public var label: String {
        switch self {
        case .onBed: "On the bed"
        case .notVisible: "Not visible"
        default: rawValue.capitalized
        }
    }
}

public enum FallState: String, Sendable {
    case possible
    case confirmed
    case rejected
    case uncertain

    public var label: String {
        switch self {
        case .possible: "Possible fall—checking"
        case .confirmed: "Fall confirmed"
        case .rejected: "Fall not confirmed"
        case .uncertain: "Uncertain—check user"
        }
    }
}

/// Exact snapshot returned by Aryan's `GET /status` contract.
public struct HubStatus: Codable, Equatable, Sendable {
    public let state: HubState
    public let level: AlertLevel
    public let timestampMilliseconds: Int64

    public init(state: HubState, level: AlertLevel, timestampMilliseconds: Int64) {
        self.state = state
        self.level = level
        self.timestampMilliseconds = timestampMilliseconds
    }

    enum CodingKeys: String, CodingKey {
        case state
        case level
        case timestampMilliseconds = "ts"
    }

    public var fallState: FallState? {
        switch level {
        case .possible: .possible
        case .confirmed: .confirmed
        case .check: .uncertain
        case .none:
            state == .rejected ? .rejected : nil
        }
    }
}

/// Exact result returned by `POST /analyze` and mirrored on `GET /events`.
public struct SpaceAnalysis: Codable, Equatable, Identifiable, Sendable {
    public let requestID: String
    public let personState: PersonState
    public let roomSummary: String
    public let riskObservations: [String]
    public let alertRecommendation: String
    public let uncertain: Bool
    public let capturedAt: String

    public var id: String { requestID }

    public var capturedAtDate: Date? {
        guard !capturedAt.isEmpty else { return nil }
        return ISO8601DateFormatter().date(from: capturedAt)
    }

    enum CodingKeys: String, CodingKey {
        case requestID = "request_id"
        case personState = "person_state"
        case roomSummary = "room_summary"
        case riskObservations = "risk_observations"
        case alertRecommendation = "alert_recommendation"
        case uncertain
        case capturedAt = "captured_at"
    }
}

public enum HubEventType: String, Codable, Sendable {
    case status
    case alert
    case analysis
}

/// One JSON object from an SSE `data:` line.
public struct HubEvent: Decodable, Sendable {
    public let type: HubEventType
    public let status: HubStatus?
    public let detail: String?
    public let analysis: SpaceAnalysis?

    enum CodingKeys: String, CodingKey {
        case type
        case state
        case level
        case timestampMilliseconds = "ts"
        case detail
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        type = try values.decode(HubEventType.self, forKey: .type)
        detail = try values.decodeIfPresent(String.self, forKey: .detail)

        switch type {
        case .status, .alert:
            status = HubStatus(
                state: try values.decode(HubState.self, forKey: .state),
                level: try values.decode(AlertLevel.self, forKey: .level),
                timestampMilliseconds: try values.decode(Int64.self, forKey: .timestampMilliseconds)
            )
            analysis = nil
        case .analysis:
            status = nil
            analysis = try SpaceAnalysis(from: decoder)
        }
    }
}

public enum HubStreamMessage: Sendable {
    case event(HubEvent)
    case heartbeat
}

public struct AcceptedAction: Decodable, Equatable, Sendable {
    public let accepted: String
}

struct HubErrorEnvelope: Decodable, Sendable {
    let error: String
}

/// App-only presentation state derived from the hub state/level pair.
public struct FallStatus: Equatable, Sendable {
    public let state: FallState
    public let updatedAt: Date
    public let detail: String?

    public init(state: FallState, updatedAt: Date, detail: String? = nil) {
        self.state = state
        self.updatedAt = updatedAt
        self.detail = detail
    }
}
