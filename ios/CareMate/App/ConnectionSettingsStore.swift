import Foundation
import Security

struct ConnectionSettings: Equatable {
    static let defaultServerAddress = "http://caremate.local:8080"

    let serverAddress: String
    let accessToken: String
}

protocol ConnectionSettingsStoring {
    func load() -> ConnectionSettings
    func save(_ settings: ConnectionSettings) throws
}

struct ConnectionSettingsStore: ConnectionSettingsStoring {
    private static let serverAddressKey = "caremate.hub.serverAddress"

    private let defaults: UserDefaults
    private let credentialStore: any CredentialStoring

    init(
        defaults: UserDefaults = .standard,
        credentialStore: any CredentialStoring = KeychainCredentialStore()
    ) {
        self.defaults = defaults
        self.credentialStore = credentialStore
    }

    func load() -> ConnectionSettings {
        let serverAddress = defaults.string(forKey: Self.serverAddressKey)
            ?? ConnectionSettings.defaultServerAddress
        let accessToken = (try? credentialStore.loadToken()) ?? ""
        return ConnectionSettings(serverAddress: serverAddress, accessToken: accessToken)
    }

    func save(_ settings: ConnectionSettings) throws {
        // Write the sensitive value first so a Keychain failure does not leave
        // partially updated connection settings behind.
        try credentialStore.saveToken(settings.accessToken)
        defaults.set(settings.serverAddress, forKey: Self.serverAddressKey)
    }
}

protocol CredentialStoring {
    func loadToken() throws -> String?
    func saveToken(_ token: String) throws
}

struct KeychainCredentialStore: CredentialStoring {
    private let service = "com.caremate.prototype.connection"
    private let account = "hub-bearer-token"

    func loadToken() throws -> String? {
        var query = baseQuery
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        switch status {
        case errSecSuccess:
            guard let data = result as? Data,
                  let token = String(data: data, encoding: .utf8) else {
                throw KeychainError.invalidData
            }
            return token
        case errSecItemNotFound:
            return nil
        default:
            throw KeychainError.operationFailed(status)
        }
    }

    func saveToken(_ token: String) throws {
        let tokenData = Data(token.utf8)
        let attributes: [String: Any] = [
            kSecValueData as String: tokenData,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        ]
        let updateStatus = SecItemUpdate(baseQuery as CFDictionary, attributes as CFDictionary)

        if updateStatus == errSecItemNotFound {
            var item = baseQuery
            attributes.forEach { item[$0.key] = $0.value }
            let addStatus = SecItemAdd(item as CFDictionary, nil)
            guard addStatus == errSecSuccess else {
                throw KeychainError.operationFailed(addStatus)
            }
        } else if updateStatus != errSecSuccess {
            throw KeychainError.operationFailed(updateStatus)
        }
    }

    private var baseQuery: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }
}

private enum KeychainError: LocalizedError {
    case invalidData
    case operationFailed(OSStatus)

    var errorDescription: String? {
        switch self {
        case .invalidData:
            "The saved hub access token could not be read."
        case let .operationFailed(status):
            "The hub access token could not be saved securely (Keychain error \(status))."
        }
    }
}
