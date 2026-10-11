import AppKit
import Combine
import Sparkle

/// Sparkle vérifie les signatures et remplace l'app ; le moteur reste géré au lancement.
@MainActor
final class AppUpdater: NSObject, ObservableObject, SPUUpdaterDelegate {
    private var controller: SPUStandardUpdaterController?
    private var observation: NSKeyValueObservation?
    @Published private(set) var canCheckForUpdates = false
    var isBusy: () -> Bool = { false }

    var isAvailable: Bool { controller != nil }
    var automaticallyChecks: Bool {
        get { controller?.updater.automaticallyChecksForUpdates ?? false }
        set { controller?.updater.automaticallyChecksForUpdates = newValue; objectWillChange.send() }
    }
    var automaticallyDownloads: Bool {
        get { controller?.updater.automaticallyDownloadsUpdates ?? false }
        set { controller?.updater.automaticallyDownloadsUpdates = newValue; objectWillChange.send() }
    }

    override init() {
        super.init()
        // Les builds locaux sans clé publique restent utilisables, sans rechercher
        // une version de production signée avec une identité différente.
        guard let key = Bundle.main.object(forInfoDictionaryKey: "SUPublicEDKey") as? String,
              !key.isEmpty,
              let feed = Bundle.main.object(forInfoDictionaryKey: "SUFeedURL") as? String,
              URL(string: feed)?.scheme == "https" else { return }
        let controller = SPUStandardUpdaterController(startingUpdater: true, updaterDelegate: self, userDriverDelegate: nil)
        self.controller = controller
        observation = controller.updater.observe(\.canCheckForUpdates, options: [.initial, .new]) { [weak self] updater, _ in
            Task { @MainActor in self?.canCheckForUpdates = updater.canCheckForUpdates }
        }
    }

    func checkForUpdates() {
        guard canCheckForUpdates, !isBusy() else { return }
        controller?.checkForUpdates(nil)
    }

    func updater(_ updater: SPUUpdater, shouldPostponeRelaunchForUpdate item: SUAppcastItem,
                 untilInvokingBlock installHandler: @escaping () -> Void) -> Bool {
        guard isBusy() else { return false }
        Task { @MainActor in
            while isBusy() { try? await Task.sleep(nanoseconds: 1_000_000_000) }
            installHandler()
        }
        return true
    }
}
