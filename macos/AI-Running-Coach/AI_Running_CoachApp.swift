import AppKit
import SwiftUI

enum DataSource: String, CaseIterable, Identifiable {
    case garmin
    case intervals

    var id: String { rawValue }
    var title: String { self == .garmin ? "Garmin Connect" : "Intervals.icu" }
    var detail: String {
        self == .garmin
            ? "Pour les montres Garmin. Synchronisation, calendrier et parcours."
            : "Pour COROS, Suunto, Polar, Apple Watch et les autres appareils reliés à Intervals.icu."
    }
}

enum IDEChoice: String, CaseIterable, Identifiable {
    case all, claude, copilot, opencode, gemini, cursor, windsurf

    var id: String { rawValue }
    var title: String {
        switch self {
        case .all: return "Je ne sais pas — tout préparer"
        case .claude: return "Claude Code"
        case .copilot: return "GitHub Copilot"
        case .opencode: return "OpenCode"
        case .gemini: return "Gemini CLI (clé API ou licence payante)"
        case .cursor: return "Cursor"
        case .windsurf: return "Windsurf"
        }
    }

    static var guidedCases: [IDEChoice] { [.claude, .copilot, .opencode, .gemini, .cursor] }

    var commandName: String {
        switch self {
        case .all, .claude: return "claude"
        case .copilot: return "copilot"
        case .opencode: return "opencode"
        case .gemini: return "gemini"
        case .cursor: return "cursor-agent"
        case .windsurf: return "windsurf"
        }
    }
}

enum CoachingStyle: String, CaseIterable, Identifiable {
    case bienveillant, exigeant, factuel, pedagogue
    var id: String { rawValue }
    var title: String {
        switch self {
        case .bienveillant: return "Encourageant"
        case .exigeant: return "Challengeant"
        case .factuel: return "Sobre et factuel"
        case .pedagogue: return "Pédagogue"
        }
    }
}

enum CoachingIntensity: String, CaseIterable, Identifiable {
    case gentle, balanced, strong
    var id: String { rawValue }
    var title: String {
        switch self {
        case .gentle: return "En douceur"
        case .balanced: return "Équilibrée"
        case .strong: return "Ferme"
        }
    }
}

enum CoachingVerbosity: String, CaseIterable, Identifiable {
    case brief, standard, detailed
    var id: String { rawValue }
    var title: String {
        switch self {
        case .brief: return "Courte"
        case .standard: return "Standard"
        case .detailed: return "Détaillée"
        }
    }
}

enum SportChoice: String, CaseIterable, Identifiable {
    case trail, road
    var id: String { rawValue }
    var title: String { self == .trail ? "Trail / ultra" : "Course sur route" }
}

enum MorningCheck: String, CaseIterable, Identifiable {
    case full, minimal, off
    var id: String { rawValue }
    var title: String {
        switch self {
        case .full: return "Complet — recommandé"
        case .minimal: return "Minimal"
        case .off: return "Désactivé"
        }
    }
}

enum UnitChoice: String, CaseIterable, Identifiable {
    case metric, imperial
    var id: String { rawValue }
    var title: String { self == .metric ? "Métriques — km, m, kg" : "Impériales — miles, pieds, livres" }
}

enum ChatChoice: String, CaseIterable, Identifiable {
    case integrated, external

    var id: String { rawValue }
    var title: String {
        switch self {
        case .integrated: return "Chat intégré dans l’application"
        case .external: return "Mon assistant IA habituel"
        }
    }
}

/// Fournisseur du chat intégré : OpenRouter (facturé à l'usage) ou l'abonnement que l'athlète a déjà
/// (ChatGPT Plus/Pro, GitHub Copilot ; connexion avec son compte par scripts/arc_llm.py, #266).
enum ChatProvider: String, CaseIterable, Identifiable {
    case openRouter, chatGPT, copilot

    var id: String { rawValue }
    var title: String {
        switch self {
        case .openRouter: return "OpenRouter"
        case .chatGPT: return "J’ai ChatGPT Plus/Pro"
        case .copilot: return "J’ai GitHub Copilot"
        }
    }
    /// Identifiant de `install.sh --llm` et de `arc_llm.py login`.
    var llmID: String {
        switch self {
        case .openRouter: return "openrouter"
        case .chatGPT: return "chatgpt"
        case .copilot: return "copilot"
        }
    }
    var isSubscription: Bool { self != .openRouter }
    var planName: String { self == .copilot ? "GitHub Copilot" : "ChatGPT" }
    /// Clé du jeton dans `auth.json` d'OpenCode (magasin dédié au coach).
    var authKey: String { self == .copilot ? "github-copilot" : "openai" }
}

/// Comment l'athlète donne accès à OpenRouter : connexion en un clic (OAuth, scripts/arc_llm.py)
/// ou clé déjà créée.
enum OpenRouterAccess: String, CaseIterable, Identifiable {
    case connect, manualKey

    var id: String { rawValue }
    var title: String {
        switch self {
        case .connect: return "Connecter OpenRouter"
        case .manualKey: return "J’ai déjà une clé"
        }
    }
}

struct ShoeChoice {
    var name = ""
    var purchaseDate = ""
    var thresholdKm = "700"
    var startingKm = "0"
    var usage = ""
}

struct SetupChoices {
    var firstName = ""
    var birthYear = ""
    var practiceYears = ""
    var weeklyAvailability = ""
    var impossibleDays = ""
    var lifeConstraints = ""
    var maxHeartRate = ""
    var restingHeartRate = ""
    var thresholdHeartRate = ""
    var vo2Max = ""
    var sex = ""
    var zones = ""
    var referencePaces = ""
    var usualWeight = ""
    var sleepNeed = ""
    var bestPerformances = ""
    var injuryHistory = ""
    var fragileAreas = ""
    var recentBreaks = ""
    var defaultLocation = ""
    var usualSlot = ""
    var accessibleTerrain = ""
    var equipment = ""
    var homeTrainer = ""
    var homeTrainerBike = ""
    var bikeMass = ""
    var declaredFtp = ""
    var crossCycling = false
    var crossSwimming = false
    var crossStrength = false
    var crossHiking = false
    var crossElliptical = false
    var crossRowing = false
    var motivation = ""
    var coachingNoGo = ""
    var sensitiveTopics = ""
    var riskTolerance = "équilibré"
    var askBeforeAssuming = ""
    var shoes = [ShoeChoice()]
    var hasObjective = true
    var raceName = ""
    var raceDate = ""
    var raceDistance = ""
    var raceElevation = ""
    var raceLocation = ""
    var raceLink = ""
    var primaryGoal = ""
    var targetTime = ""
    var acceptableScenario = ""
    var weeksRemaining = ""
    var startingVolume = ""
    var targetVolume = ""
    var qualitySessions = ""
    var objectiveUnavailability = ""
    var intermediateRaces = ""
    var medicalLimits = ""
    var chatChoice: ChatChoice = .integrated
    var chatProvider: ChatProvider = .openRouter
    /// Abonnement : la synchronisation automatique passe aussi sur le forfait (`--sync-subscription`).
    /// L'application n'a pas d'autre exécuteur de synchronisation dans ce mode.
    var syncWithSubscription = true
    var openRouterAccess: OpenRouterAccess = .connect
    var openRouterAPIKey = ""
    var chatBudget = "1.00"
    var source: DataSource = .garmin
    var ide: IDEChoice = .claude
    var coachingStyle: CoachingStyle = .bienveillant
    var coachingIntensity: CoachingIntensity = .balanced
    var coachingVerbosity: CoachingVerbosity = .standard
    var sport: SportChoice = .trail
    var morningCheck: MorningCheck = .full
    var documentsLanguage = "fr"
    var responsesLanguage = "auto"
    var units: UnitChoice = .metric
    var medical = true
    var nutritionist = true
    var strategist = true
    var workspace: String = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Documents/AI Running Coach").path

    var agents: [String] {
        var result = ["coach"]
        if medical { result.append("medical") }
        if nutritionist { result.append("nutritionist") }
        if strategist { result.append("course-strategist") }
        return result
    }

    var disciplines: [String] {
        var result: [String] = []
        if crossCycling { result.append("cycling") }
        if crossSwimming { result.append("swimming") }
        if crossStrength { result.append("strength") }
        if crossHiking { result.append("hiking") }
        if crossElliptical { result.append("elliptical") }
        if crossRowing { result.append("rowing") }
        return result
    }

    var disciplinesLabel: String {
        let labels = [
            crossCycling ? "vélo" : nil,
            crossSwimming ? "natation" : nil,
            crossStrength ? "renforcement" : nil,
            crossHiking ? "randonnée" : nil,
            crossElliptical ? "elliptique" : nil,
            crossRowing ? "rameur" : nil
        ].compactMap { $0 }
        return labels.joined(separator: ", ")
    }

    var profileIsCompleteEnough: Bool {
        [firstName, birthYear, practiceYears, weeklyAvailability, defaultLocation]
            .allSatisfy { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }

    var objectiveIsCompleteEnough: Bool {
        !hasObjective || [raceName, raceDate, raceDistance, primaryGoal]
            .allSatisfy { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }

    var chatIsCompleteEnough: Bool {
        guard chatChoice == .integrated else { return true }
        if chatProvider.isSubscription { return true }   // abonnement : ni clé ni plafond en euros
        if openRouterAccess == .manualKey {
            let key = openRouterAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !key.isEmpty, !key.contains("\n"), !key.contains("\r") else { return false }
        }
        guard let budget = Double(chatBudget.replacingOccurrences(of: ",", with: ".")) else { return false }
        return budget > 0
    }

    var syncRunner: String {
        guard chatChoice == .external else { return IDEChoice.opencode.rawValue }
        return ide == .all ? IDEChoice.claude.rawValue : ide.rawValue
    }
}

private final class OutputBuffer: @unchecked Sendable {
    private let lock = NSLock()
    private var data = Data()

    func append(_ chunk: Data) {
        lock.lock()
        data.append(chunk)
        lock.unlock()
    }

    func string() -> String {
        lock.lock()
        let snapshot = data
        lock.unlock()
        return String(data: snapshot, encoding: .utf8) ?? ""
    }
}

/// Issue de la connexion OpenRouter (arc_llm.py : 0 connecté, 6 clé écrite mais non vérifiée).
private enum ConnectOutcome {
    case connected(String)
    case unverified(String)
    case failed(String)
}

/// Découpe un flux en lignes complètes : une ligne peut arriver en plusieurs lectures.
private final class LineBuffer: @unchecked Sendable {
    private var pending = ""
    private let lock = NSLock()
    func append(_ data: Data) -> [String] {
        lock.lock(); defer { lock.unlock() }
        pending += String(decoding: data, as: UTF8.self)
        var lines = pending.components(separatedBy: "\n")
        pending = lines.removeLast()
        return lines.filter { !$0.isEmpty }
    }
}

private enum ConnectRecovery { case retry, manualKey, skipChat }

private struct ProcessResult {
    let code: Int32
    let output: String
}

@MainActor
final class CoachAppModel: ObservableObject {
    enum Phase { case welcome, installing, ready, failed }

    @Published var phase: Phase = .welcome
    @Published var choices = SetupChoices()
    @Published var progress = 0.0
    @Published var progressTitle = "Préparation"
    @Published var log = ""
    @Published var errorMessage = ""
    @Published var dashboardRunning = false
    @Published var diagnostics = ""
    @Published var showDiagnostics = false
    let appUpdater = AppUpdater()
    @Published var updateAvailable = false
    @Published var updateWaiting = false
    private var automaticUpdateAttempted = false

    var operationInProgress: Bool {
        phase == .installing || manualSyncRunning || enrichmentSaving || enrichmentLoading
    }

    func applyPendingEngineUpdate() {
        guard updateAvailable, !automaticUpdateAttempted, !operationInProgress else { return }
        automaticUpdateAttempted = true
        updateEngine()
    }
    @Published private(set) var wasUpdating = false
    @Published var showOptionalProfile = false
    @Published var showEnrichment = false
    @Published var enrichmentLoading = false
    @Published var enrichmentSaving = false
    @Published var enrichmentError = ""
    @Published var manualSyncRunning = false
    @Published var manualSyncStatus = ""
    @Published var manualSyncFailed = false

    @Published var connecting = false
    @Published var connectURL: URL?
    private var connectProcess: Process?
    private var connectCancelled = false
    private var dashboardProcess: Process?
    private var dashboardBaseURL: URL?
    private let fm = FileManager.default
    private let defaults = UserDefaults.standard

    var appSupport: URL {
        fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("AI Running Coach", isDirectory: true)
    }

    var engineURL: URL { appSupport.appendingPathComponent("engine", isDirectory: true) }
    var workspaceURL: URL { URL(fileURLWithPath: choices.workspace).standardizedFileURL }
    var bundleVersion: String { Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "development" }
    var engineBuild: String { Bundle.main.object(forInfoDictionaryKey: "ARCEngineBuild") as? String ?? bundleVersion }

    var engineRecoveryPending: Bool {
        fm.fileExists(atPath: appSupport.appendingPathComponent("engine.previous").path)
    }

    var isInstalled: Bool {
        (fm.isExecutableFile(atPath: engineURL.appendingPathComponent("install.sh").path)
            || fm.isExecutableFile(atPath: appSupport.appendingPathComponent("engine.previous/install.sh").path))
            && fm.fileExists(atPath: workspaceURL.appendingPathComponent("config/workspace.user.toml").path)
    }

    var isAuthenticated: Bool {
        if choices.source == .garmin {
            return fm.fileExists(atPath: fm.homeDirectoryForCurrentUser
                .appendingPathComponent(".garminconnect/garmin_tokens.json").path)
        }
        return fm.fileExists(atPath: fm.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/ai-running-coach/intervals-icu-mcp/.env").path)
    }

    var integratedChatEnabled: Bool { defaults.bool(forKey: "integratedChatEnabled") }
    /// Chat intégré choisi mais pas encore connecté : ni chat ni synchronisation en arrière-plan
    /// (elle passerait par OpenCode, sans clé) tant que « Connecter OpenRouter » n'a pas abouti.
    var integratedChatPending: Bool { defaults.bool(forKey: "integratedChatPending") }

    /// Sondage de l'état de la connexion (un seul à la fois : un nouveau clic annule le précédent).
    var subscriptionPoll: Task<Void, Never>?

    /// Magasin d'authentification OpenCode du coach (même chemin que `install.sh`, #266).
    var coachOpenCodeStore: URL {
        fm.homeDirectoryForCurrentUser.appendingPathComponent(".local/share/ai-running-coach/opencode", isDirectory: true)
    }
    /// Abonnement choisi pour le chat intégré (nil = OpenRouter ou assistant externe).
    var savedChatProvider: ChatProvider? {
        guard integratedChatEnabled, let raw = defaults.string(forKey: "chatProvider"),
              let provider = ChatProvider(rawValue: raw), provider.isSubscription else { return nil }
        return provider
    }
    /// Le jeton est-il dans le magasin ? Présence de la clé seulement, jamais sa valeur.
    var subscriptionConnected: Bool {
        guard let provider = savedChatProvider,
              let data = try? Data(contentsOf: coachOpenCodeStore.appendingPathComponent("opencode/auth.json")),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return false }
        // Seule une connexion de type « oauth » (abonnement) compte, pas une clé API rangée là.
        return (object[provider.authKey] as? [String: Any])?["type"] as? String == "oauth"
    }
    var externalAssistantTitle: String { choices.ide.title }
    var syncStatusDetail: String {
        integratedChatEnabled ? "Automatique" : "Après la 1re connexion à \(externalAssistantTitle)"
    }

    init() {
        if let saved = defaults.string(forKey: "workspace"), !saved.isEmpty {
            choices.workspace = saved
        }
        if let saved = defaults.string(forKey: "source"), let source = DataSource(rawValue: saved) {
            choices.source = source
        }
        if let saved = defaults.string(forKey: "assistant"), let assistant = IDEChoice(rawValue: saved) {
            choices.ide = assistant
        }
        let installed = isInstalled
        if installed {
            choices.chatChoice = defaults.bool(forKey: "integratedChatEnabled") ? .integrated : .external
            if let raw = defaults.string(forKey: "chatProvider"), let provider = ChatProvider(rawValue: raw) {
                choices.chatProvider = provider
            }
            if defaults.object(forKey: "syncWithSubscription") != nil {
                choices.syncWithSubscription = defaults.bool(forKey: "syncWithSubscription")
            }
        }
        phase = installed ? .ready : .welcome
        updateAvailable = installed && (
            engineRecoveryPending || defaults.string(forKey: "engineVersion") != bundleVersion
            || defaults.string(forKey: "engineBuild") != engineBuild
        )
        appUpdater.isBusy = { [weak self] in self?.operationInProgress ?? false }
        NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.dashboardProcess?.terminate() }
        }
        NotificationCenter.default.addObserver(
            forName: NSApplication.didBecomeActiveNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.objectWillChange.send() }
        }
    }

    func chooseWorkspace() {
        let panel = NSOpenPanel()
        panel.title = "Choisir le dossier de vos données"
        panel.prompt = "Choisir"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.directoryURL = workspaceURL.deletingLastPathComponent()
        if panel.runModal() == .OK, let url = panel.url {
            choices.workspace = url.path
        }
    }

    func install() {
        wasUpdating = false
        phase = .installing
        progress = 0.05
        log = ""
        errorMessage = ""
        let selected = choices
        let installationIDE: IDEChoice = selected.chatChoice == .integrated ? .opencode : selected.ide

        Task {
            do {
                var chatEnabled = selected.chatChoice == .integrated
                try await ensureDeveloperTools()
                try await installEngine()
                if selected.chatChoice == .integrated {
                    progress = 0.16
                    progressTitle = "Préparation du chat avec le coach"
                    if selected.chatProvider.isSubscription {
                        // Abonnement ChatGPT / Copilot : aucune clé. La connexion se fait dans Terminal
                        // une fois l'installation terminée (arc_llm.py login).
                        appendLog("Chat sur votre abonnement \(selected.chatProvider.planName) : aucune clé API à fournir.\n")
                    } else if selected.openRouterAccess == .connect {
                        // Le moteur vient d'être extrait : arc_llm.py est disponible. La connexion
                        // se fait avant l'activation du chat ; un échec propose de réessayer, de
                        // coller une clé ou de continuer sans le chat (à connecter plus tard).
                        chatEnabled = await obtainOpenRouterAccess()
                    } else {
                        try saveOpenRouterKey(selected.openRouterAPIKey)
                    }
                    try await ensureOpenCode()
                } else {
                    progress = 0.16
                    progressTitle = "Installation de \(selected.ide.title)"
                    try await ensureExternalAssistant(selected.ide)
                }
                progress = 0.22
                progressTitle = "Installation des composants"

                try fm.createDirectory(at: selected.workspace.isEmpty ? workspaceURL : URL(fileURLWithPath: selected.workspace), withIntermediateDirectories: true)
                var args = [
                    "--workspace", selected.workspace,
                    "--source", selected.source.rawValue,
                    "--ide", installationIDE.rawValue,
                    "--agents", selected.agents.joined(separator: ","),
                    "--no-auth"
                ]
                let chatPending = selected.chatChoice == .integrated && !chatEnabled
                let subscriptionChat = selected.chatChoice == .integrated && selected.chatProvider.isSubscription
                if !chatPending && (!subscriptionChat || selected.syncWithSubscription) {
                    args += ["--daily-sync", "--sync-runner", selected.syncRunner]
                }
                if subscriptionChat {
                    // Pas de plafond en euros : rien n'est facturé au jeton.
                    args += ["--llm", selected.chatProvider.llmID, "--chat"]
                    // Case décochée : install.sh ne doit pas déplacer la synchronisation, même sur une installation neuve.
                    args += [selected.syncWithSubscription ? "--sync-subscription" : "--no-sync-subscription"]
                } else if selected.chatChoice == .integrated {
                    args += ["--llm", "openrouter"]
                    if chatEnabled {
                        args += [
                            "--chat",
                            "--chat-budget", selected.chatBudget.replacingOccurrences(of: ",", with: ".")
                        ]
                    }
                }
                let result = try await runProcess(
                    executable: "/bin/bash",
                    arguments: [engineURL.appendingPathComponent("install.sh").path] + args,
                    directory: engineURL,
                    streamOutput: true
                )
                guard result.code == 0 else { throw AppFailure("L’installation des composants s’est arrêtée (code \(result.code)).") }

                progress = 0.78
                progressTitle = "Application de vos préférences"
                try await applyConfiguration(selected)
                try await applyAthleteProfile(selected)
                try await applyShoes(selected)
                try await applyObjective(selected)

                defaults.set(selected.workspace, forKey: "workspace")
                defaults.set(selected.source.rawValue, forKey: "source")
                defaults.set(chatEnabled, forKey: "integratedChatEnabled")
                defaults.set(chatPending, forKey: "integratedChatPending")
                if chatPending {
                    appendLog("Le chat ET la synchronisation en arrière-plan attendent la connexion OpenRouter : utilisez « Connecter OpenRouter » sur l’écran d’accueil.\n")
                }
                defaults.set(selected.chatProvider.rawValue, forKey: "chatProvider")
                defaults.set(selected.syncWithSubscription, forKey: "syncWithSubscription")
                defaults.set(installationIDE.rawValue, forKey: "assistant")
                defaults.set(bundleVersion, forKey: "engineVersion")
                defaults.set(engineBuild, forKey: "engineBuild")
                choices.openRouterAPIKey = ""
                updateAvailable = false
                progress = 1
                progressTitle = "Installation terminée"
                phase = .ready
                if selected.chatChoice == .integrated && selected.chatProvider.isSubscription {
                    connectSubscription()   // ouvre Terminal pour la connexion avec le compte
                }
            } catch {
                errorMessage = error.localizedDescription
                appendLog("\nErreur : \(error.localizedDescription)\n")
                phase = .failed
            }
        }
    }

    func updateEngine() {
        guard !operationInProgress else { return }
        updateWaiting = false
        wasUpdating = true
        phase = .installing
        progress = 0.05
        progressTitle = "Mise à jour du moteur"
        log = ""
        errorMessage = ""
        Task {
            do {
                try await ensureDeveloperTools()
                guard let helper = Bundle.main.url(forResource: "arc_engine_update", withExtension: "py"),
                      let archive = Bundle.main.url(forResource: "engine", withExtension: "tar.gz") else {
                    throw AppFailure("Le moteur embarqué est introuvable. Téléchargez à nouveau l’application.")
                }
                dashboardProcess?.terminate()
                dashboardProcess = nil
                dashboardBaseURL = nil
                dashboardRunning = false
                progress = 0.35
                progressTitle = "Vérification des composants"
                var args = [
                    "python3", helper.path,
                    "--archive", archive.path, "--engine", engineURL.path,
                    "--workspace", workspaceURL.path, "--",
                    "--workspace", workspaceURL.path,
                    "--source", choices.source.rawValue,
                    "--ide", integratedChatPending ? IDEChoice.opencode.rawValue : (integratedChatEnabled ? IDEChoice.opencode.rawValue : choices.ide.rawValue),
                    "--no-auth"
                ]
                if !integratedChatPending && (savedChatProvider == nil || choices.syncWithSubscription) {
                    args += ["--daily-sync", "--sync-runner", choices.syncRunner]
                }
                let result = try await runProcess(
                    executable: "/usr/bin/env",
                    arguments: args,
                    directory: appSupport,
                    streamOutput: true
                )
                if result.code == 75 {
                    updateWaiting = true
                    phase = .ready
                    Task { @MainActor in
                        while updateWaiting {
                            try? await Task.sleep(nanoseconds: 30_000_000_000)
                            if updateWaiting && !operationInProgress {
                                updateEngine()
                                return
                            }
                        }
                    }
                    return
                }
                guard result.code == 0 else { throw AppFailure("La mise à jour s’est arrêtée (code \(result.code)).") }
                defaults.set(bundleVersion, forKey: "engineVersion")
                defaults.set(engineBuild, forKey: "engineBuild")
                updateAvailable = false
                progress = 1
                progressTitle = "Mise à jour terminée"
                phase = .ready
            } catch {
                errorMessage = error.localizedDescription
                appendLog("\nErreur : \(error.localizedDescription)\n")
                phase = .failed
            }
        }
    }

    func saveEnrichment() {
        enrichmentSaving = true
        enrichmentError = ""
        let selected = choices
        Task {
            do {
                try await applyAthleteProfile(selected)
                try await applyShoes(selected)
                try await applyObjective(selected)
                enrichmentSaving = false
                showEnrichment = false
            } catch {
                enrichmentSaving = false
                enrichmentError = error.localizedDescription
            }
        }
    }

    func openEnrichment() {
        guard !enrichmentLoading else { return }
        enrichmentLoading = true
        enrichmentError = ""
        Task {
            do {
                let result = try await runProcess(
                    executable: "/usr/bin/env",
                    arguments: [
                        "python3",
                        engineURL.appendingPathComponent("scripts/coach_setup.py").path,
                        "--workspace", workspaceURL.path,
                        "--export-state"
                    ],
                    directory: engineURL,
                    streamOutput: false
                )
                // Ne jamais remplacer le moteur depuis ce parcours : la mise à
                // jour dédiée prend le verrou de synchronisation et garde un secours.
                if result.code == 2 {
                    throw AppFailure("Mettez à jour le moteur depuis l’accueil, puis réessayez.")
                }
                guard result.code == 0,
                      let data = result.output.data(using: .utf8),
                      let state = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    throw AppFailure("Les informations enregistrées n’ont pas pu être relues.")
                }
                applyEnrichmentState(state)
                showOptionalProfile = true
            } catch {
                enrichmentError = "Impossible de préremplir le formulaire : \(error.localizedDescription)"
            }
            enrichmentLoading = false
            showEnrichment = true
        }
    }

    private func applyEnrichmentState(_ state: [String: Any]) {
        let profile = state["profile"] as? [String: Any] ?? [:]
        let objective = state["objective"] as? [String: Any] ?? [:]
        func value(_ source: [String: Any], _ key: String) -> String {
            if let text = source[key] as? String { return text }
            if let number = source[key] as? NSNumber { return number.stringValue }
            return ""
        }

        choices.firstName = value(profile, "prenom / surnom")
        choices.birthYear = value(profile, "annee de naissance")
        choices.practiceYears = value(profile, "annees de pratique")
        choices.weeklyAvailability = value(profile, "disponibilite hebdomadaire")
        choices.impossibleDays = value(profile, "jours impossibles")
        choices.lifeConstraints = value(profile, "contraintes de vie")
        choices.maxHeartRate = value(profile, "fc max")
        choices.restingHeartRate = value(profile, "fc de repos de reference")
        choices.thresholdHeartRate = value(profile, "fc au seuil")
        choices.vo2Max = value(profile, "vo2max (garmin)")
        choices.sex = value(profile, "sexe")
        choices.zones = value(profile, "zones / seuils")
        choices.referencePaces = value(profile, "allures de reference")
        choices.usualWeight = value(profile, "poids de forme")
        choices.sleepNeed = value(profile, "besoin de sommeil")
        choices.bestPerformances = value(profile, "meilleures performances")
        choices.injuryHistory = value(profile, "antecedents de blessure")
        choices.fragileAreas = value(profile, "zones fragiles a surveiller")
        choices.recentBreaks = value(profile, "arrets recents")
        choices.defaultLocation = value(profile, "lieu par defaut")
        choices.usualSlot = value(profile, "creneau habituel")
        choices.accessibleTerrain = value(profile, "terrain accessible")
        choices.equipment = value(profile, "equipement")
        choices.homeTrainer = value(profile, "home trainer")
        choices.homeTrainerBike = value(profile, "velo sur home trainer")
        choices.bikeMass = value(profile, "masse du velo")
        choices.declaredFtp = value(profile, "ftp declaree")
        choices.motivation = value(profile, "ce qui me motive")
        choices.coachingNoGo = value(profile, "ce qui ne marche pas avec moi")
        choices.sensitiveTopics = value(profile, "sujets a ne pas commenter spontanement")
        choices.riskTolerance = value(profile, "tolerance au risque")
        choices.askBeforeAssuming = value(profile, "quand me poser une question plutot que supposer")

        let disciplines = Set(value(profile, "sports croises pratiques")
            .lowercased().split { $0 == "," || $0 == ";" }.map { $0.trimmingCharacters(in: .whitespaces) })
        choices.crossCycling = disciplines.contains("velo") || disciplines.contains("vélo") || disciplines.contains("cycling")
        choices.crossSwimming = disciplines.contains("natation") || disciplines.contains("swimming")
        choices.crossStrength = disciplines.contains("renforcement") || disciplines.contains("strength")
        choices.crossHiking = disciplines.contains("randonnee") || disciplines.contains("randonnée") || disciplines.contains("hiking")
        choices.crossElliptical = disciplines.contains("elliptique") || disciplines.contains("elliptical")
        choices.crossRowing = disciplines.contains("rameur") || disciplines.contains("rowing")

        choices.raceName = value(objective, "nom")
        choices.raceDate = value(objective, "date")
        choices.raceDistance = value(objective, "distance")
        choices.raceElevation = value(objective, "denivele positif")
        choices.raceLocation = value(objective, "lieu")
        choices.raceLink = value(objective, "lien / trace gpx")
        choices.primaryGoal = value(objective, "objectif principal")
        choices.targetTime = value(objective, "temps vise")
        choices.acceptableScenario = value(objective, "scenario acceptable / scenario noir")
        choices.weeksRemaining = value(objective, "semaines restantes")
        choices.startingVolume = value(objective, "volume hebdomadaire de depart")
        choices.targetVolume = value(objective, "volume hebdomadaire cible")
        choices.qualitySessions = value(objective, "seances qualite par semaine")
        choices.objectiveUnavailability = value(objective, "indisponibilites")
        choices.intermediateRaces = value(objective, "courses intermediaires")
        choices.medicalLimits = value(objective, "limites medicales en cours")
        choices.hasObjective = !objective.isEmpty

        if let storedShoes = state["shoes"] as? [[String: Any]], !storedShoes.isEmpty {
            choices.shoes = storedShoes.map { shoe in
                ShoeChoice(
                    name: value(shoe, "name"),
                    purchaseDate: value(shoe, "purchase_date"),
                    thresholdKm: value(shoe, "threshold_km"),
                    startingKm: value(shoe, "starting_km"),
                    usage: value(shoe, "usage")
                )
            }
        } else {
            choices.shoes = [ShoeChoice()]
        }
    }

    private func ensureDeveloperTools() async throws {
        let check = try await runProcess(
            executable: "/usr/bin/xcode-select",
            arguments: ["-p"],
            directory: fm.homeDirectoryForCurrentUser,
            streamOutput: false
        )
        guard check.code != 0 else { return }
        appendLog("macOS doit ajouter ses outils système gratuits (Git et Python).\n")
        _ = try await runProcess(
            executable: "/usr/bin/xcode-select",
            arguments: ["--install"],
            directory: fm.homeDirectoryForCurrentUser,
            streamOutput: false
        )
        throw AppFailure("macOS vient d’ouvrir l’installation de ses outils système. Terminez-la, puis cliquez sur Réessayer.")
    }

    private func installEngine() async throws {
        progressTitle = "Préparation du moteur"
        guard let archive = Bundle.main.url(forResource: "engine", withExtension: "tar.gz") else {
            throw AppFailure("Le moteur embarqué est introuvable. Téléchargez à nouveau l’application.")
        }
        try fm.createDirectory(at: appSupport, withIntermediateDirectories: true)
        let stage = appSupport.appendingPathComponent("engine-stage-\(UUID().uuidString)", isDirectory: true)
        let backup = appSupport.appendingPathComponent("engine-backup", isDirectory: true)
        try fm.createDirectory(at: stage, withIntermediateDirectories: true)

        let result = try await runProcess(
            executable: "/usr/bin/tar",
            arguments: ["-xzf", archive.path, "-C", stage.path],
            directory: appSupport,
            streamOutput: false
        )
        guard result.code == 0, fm.fileExists(atPath: stage.appendingPathComponent("install.sh").path) else {
            try? fm.removeItem(at: stage)
            throw AppFailure("Impossible de préparer les fichiers de l’application.")
        }

        try? fm.removeItem(at: backup)
        if fm.fileExists(atPath: engineURL.path) {
            try fm.moveItem(at: engineURL, to: backup)
        }
        do {
            try fm.moveItem(at: stage, to: engineURL)
            try? fm.removeItem(at: backup)
        } catch {
            if fm.fileExists(atPath: backup.path) && !fm.fileExists(atPath: engineURL.path) {
                try? fm.moveItem(at: backup, to: engineURL)
            }
            throw error
        }
    }

    /// Vrai si llm.env contient déjà une clé OpenRouter non vide (évite un doublon sur « Réessayer »).
    private func hasOpenRouterKey() -> Bool {
        let file = fm.homeDirectoryForCurrentUser.appendingPathComponent(".config/ai-running-coach/llm.env")
        guard let text = try? String(contentsOf: file, encoding: .utf8) else { return false }
        for raw in text.split(separator: "\n") {
            var line = raw.trimmingCharacters(in: .whitespaces)
            if line.hasPrefix("export ") { line = String(line.dropFirst(7)).trimmingCharacters(in: .whitespaces) }
            if line.hasPrefix("OPENROUTER_API_KEY=") {
                return !line.dropFirst("OPENROUTER_API_KEY=".count).trimmingCharacters(in: .whitespaces).isEmpty
            }
        }
        return false
    }

    /// Obtient l'accès OpenRouter par connexion. Renvoie false si l'athlète choisit de continuer
    /// sans le chat (il pourra se connecter plus tard).
    private func obtainOpenRouterAccess() async -> Bool {
        if hasOpenRouterKey() {
            appendLog("Une clé OpenRouter est déjà enregistrée : connexion ignorée.\n")
            return true
        }
        while true {
            // Re-vérifié à chaque tentative : une tentative précédente a pu écrire la clé.
            if hasOpenRouterKey() {
                appendLog("Une clé OpenRouter est maintenant enregistrée : connexion terminée.\n")
                return true
            }
            switch await connectOpenRouter() {
            case .connected(let message):
                appendLog("\(message)\n")
                return true
            case .unverified(let message):
                appendLog("Attention : \(message)\n")
                return true
            case .failed(let message):
                appendLog("\(message)\n")
                var note = message
                recovery: while true {
                    switch askConnectionRecovery(note) {
                    case .retry:
                        break recovery
                    case .manualKey:
                        if let key = askManualKey(), (try? saveOpenRouterKey(key)) != nil { return true }
                        note = "Clé vide ou invalide. Réessayez la connexion, collez une clé valide ou continuez sans le chat."
                        appendLog("\(note)\n")
                    case .skipChat:
                        appendLog("Le chat intégré et la synchronisation en arrière-plan ne sont pas activés. Utilisez « Connecter OpenRouter » sur l’écran d’accueil pour les activer.\n")
                        return false
                    }
                }
            }
        }
    }

    private func askConnectionRecovery(_ message: String) -> ConnectRecovery {
        let alert = NSAlert()
        alert.messageText = "La connexion à OpenRouter n’a pas abouti"
        alert.informativeText = message
        alert.addButton(withTitle: "Réessayer la connexion")
        alert.addButton(withTitle: "J’ai déjà une clé")
        alert.addButton(withTitle: "Continuer sans le chat")
        switch alert.runModal() {
        case .alertFirstButtonReturn: return .retry
        case .alertSecondButtonReturn: return .manualKey
        default: return .skipChat
        }
    }

    private func askManualKey() -> String? {
        let alert = NSAlert()
        alert.messageText = "Clé OpenRouter"
        alert.informativeText = "Collez votre clé. Elle reste sur ce Mac, dans un fichier privé."
        let field = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 320, height: 24))
        alert.accessoryView = field
        alert.addButton(withTitle: "Enregistrer")
        alert.addButton(withTitle: "Annuler")
        guard alert.runModal() == .alertFirstButtonReturn else { return nil }
        return field.stringValue
    }

    /// Écran d'accueil : connexion différée après un « Continuer sans le chat ». Une fois la clé
    /// obtenue, install.sh active le chat et la synchronisation OpenCode.
    func connectChatLater() {
        guard !operationInProgress else { return }
        wasUpdating = true
        phase = .installing
        progress = 0.05
        progressTitle = "Connexion à OpenRouter"
        log = ""
        errorMessage = ""
        Task {
            do {
                guard await obtainOpenRouterAccess() else { phase = .ready; return }
                progress = 0.6
                progressTitle = "Activation du chat et de la synchronisation"
                let budget = choices.chatBudget.replacingOccurrences(of: ",", with: ".")
                let result = try await runProcess(
                    executable: "/bin/bash",
                    arguments: [engineURL.appendingPathComponent("install.sh").path,
                                "--workspace", workspaceURL.path,
                                "--source", choices.source.rawValue,
                                "--ide", IDEChoice.opencode.rawValue,
                                "--no-auth", "--daily-sync", "--sync-runner", IDEChoice.opencode.rawValue,
                                "--llm", "openrouter", "--chat", "--chat-budget", budget],
                    directory: engineURL,
                    streamOutput: true
                )
                guard result.code == 0 else { throw AppFailure("L’activation du chat s’est arrêtée (code \(result.code)).") }
                defaults.set(true, forKey: "integratedChatEnabled")
                defaults.set(false, forKey: "integratedChatPending")
                progress = 1
                progressTitle = "Chat connecté"
                phase = .ready
            } catch {
                errorMessage = error.localizedDescription
                appendLog("\nErreur : \(error.localizedDescription)\n")
                phase = .failed
            }
        }
    }

    func cancelConnection() {
        connectCancelled = true
        connectProcess?.terminate()
    }

    /// Connexion OpenRouter en un clic : `arc_llm.py connect openrouter --json`. La clé est écrite
    /// dans llm.env par le script ; l'application ne la voit jamais (la sortie n'en contient pas).
    /// Les événements JSON (stderr) donnent l'adresse d'autorisation ; l'objet final est sur stdout.
    private func connectOpenRouter() async -> ConnectOutcome {
        progress = 0.18
        progressTitle = "Connexion à OpenRouter : autorisez le coach dans votre navigateur"
        appendLog("Connexion à OpenRouter : une page s’ouvre dans votre navigateur.\n")
        connectCancelled = false
        connectURL = nil
        connecting = true
        defer { connecting = false; connectURL = nil; connectProcess = nil }
        let script = engineURL.appendingPathComponent("scripts/arc_llm.py").path
        let directory = engineURL
        let environment = processEnvironment()
        return await withCheckedContinuation { (continuation: CheckedContinuation<ConnectOutcome, Never>) in
            let process = Process()
            let stdout = Pipe()
            let stderr = Pipe()
            let buffer = OutputBuffer()
            let eventLines = LineBuffer()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            process.arguments = ["python3", script, "connect", "openrouter", "--json"]
            process.currentDirectoryURL = directory
            process.environment = environment
            process.standardOutput = stdout
            process.standardError = stderr
            stdout.fileHandleForReading.readabilityHandler = { handle in
                let data = handle.availableData
                if !data.isEmpty { buffer.append(data) }
            }
            stderr.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let data = handle.availableData
                guard !data.isEmpty else { return }
                for line in eventLines.append(data) {
                    guard let lineData = line.data(using: .utf8),
                          let event = try? JSONSerialization.jsonObject(with: lineData) as? [String: Any],
                          event["event"] as? String == "auth_url",
                          event["browser_opened"] as? Bool == false,
                          let raw = event["url"] as? String, let url = URL(string: raw) else { continue }
                    Task { @MainActor in self?.connectURL = url }
                }
            }
            process.terminationHandler = { [weak self] process in
                stdout.fileHandleForReading.readabilityHandler = nil
                stderr.fileHandleForReading.readabilityHandler = nil
                buffer.append(stdout.fileHandleForReading.readDataToEndOfFile())
                var final: [String: Any]?
                for line in buffer.string().split(separator: "\n") {
                    guard let data = line.data(using: .utf8),
                          let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                          object["ok"] != nil else { continue }
                    final = object
                }
                let message = (final?["message"] as? String) ?? "Réponse inattendue du script de connexion."
                let code = process.terminationStatus
                Task { @MainActor in
                    if self?.connectCancelled == true {
                        continuation.resume(returning: .failed("Connexion annulée."))
                    } else if code == 0, final?["ok"] as? Bool == true {
                        continuation.resume(returning: .connected(message))
                    } else if code == 6 {
                        continuation.resume(returning: .unverified(message))
                    } else {
                        continuation.resume(returning: .failed(message))
                    }
                }
            }
            do {
                try process.run()
                connectProcess = process
            } catch {
                stdout.fileHandleForReading.readabilityHandler = nil
                stderr.fileHandleForReading.readabilityHandler = nil
                continuation.resume(returning: .failed("Impossible de lancer la connexion : \(error.localizedDescription)"))
            }
        }
    }

    private func saveOpenRouterKey(_ rawKey: String) throws {
        let key = rawKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty, !key.contains("\n"), !key.contains("\r") else {
            throw AppFailure("La clé OpenRouter est vide ou invalide.")
        }
        let directory = fm.homeDirectoryForCurrentUser.appendingPathComponent(".config/ai-running-coach", isDirectory: true)
        let file = directory.appendingPathComponent("llm.env")
        try fm.createDirectory(
            at: directory,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        let previous = (try? String(contentsOf: file, encoding: .utf8)) ?? ""
        let kept = previous.split(separator: "\n", omittingEmptySubsequences: false).filter { line in
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            return !trimmed.hasPrefix("OPENROUTER_API_KEY=") && !trimmed.hasPrefix("export OPENROUTER_API_KEY=")
        }
        let contents = kept.joined(separator: "\n").trimmingCharacters(in: .newlines)
            + (kept.isEmpty ? "" : "\n") + "OPENROUTER_API_KEY=\(key)\n"
        let temporary = directory.appendingPathComponent(".llm.env.\(UUID().uuidString)")
        guard fm.createFile(
            atPath: temporary.path,
            contents: contents.data(using: .utf8),
            attributes: [.posixPermissions: 0o600]
        ) else {
            throw AppFailure("La clé OpenRouter n’a pas pu être enregistrée.")
        }
        do {
            if fm.fileExists(atPath: file.path) {
                _ = try fm.replaceItemAt(file, withItemAt: temporary)
            } else {
                try fm.moveItem(at: temporary, to: file)
            }
            try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        } catch {
            try? fm.removeItem(at: temporary)
            throw error
        }
    }

    private func ensureOpenCode() async throws {
        let check = try await runProcess(
            executable: "/usr/bin/which",
            arguments: ["opencode"],
            directory: appSupport,
            streamOutput: false
        )
        guard check.code != 0 else { return }
        appendLog("Installation du composant qui permet de discuter avec le coach…\n")
        let installer = appSupport.appendingPathComponent("opencode-install.sh")
        defer { try? fm.removeItem(at: installer) }
        let download = try await runProcess(
            executable: "/usr/bin/curl",
            arguments: ["-fsSL", "https://opencode.ai/v2/install", "-o", installer.path],
            directory: appSupport,
            streamOutput: true
        )
        guard download.code == 0 else { throw AppFailure("Impossible de télécharger le composant du chat.") }
        let install = try await runProcess(
            executable: "/bin/sh",
            arguments: [installer.path],
            directory: appSupport,
            streamOutput: true
        )
        guard install.code == 0 else { throw AppFailure("Impossible d’installer le composant du chat.") }
        let verify = try await runProcess(
            executable: "/usr/bin/which",
            arguments: ["opencode"],
            directory: appSupport,
            streamOutput: false
        )
        guard verify.code == 0 else { throw AppFailure("Le composant du chat a été installé mais reste introuvable. Relancez l’application.") }
    }

    private func commandExists(_ command: String) async throws -> Bool {
        let result = try await runProcess(
            executable: "/usr/bin/which",
            arguments: [command],
            directory: appSupport,
            streamOutput: false
        )
        return result.code == 0
    }

    private func installOfficialScript(url: String, name: String) async throws {
        let installer = appSupport.appendingPathComponent("\(name)-install.sh")
        defer { try? fm.removeItem(at: installer) }
        let download = try await runProcess(
            executable: "/usr/bin/curl",
            arguments: ["-fsSL", url, "-o", installer.path],
            directory: appSupport,
            streamOutput: true
        )
        guard download.code == 0 else { throw AppFailure("Impossible de télécharger \(name).") }
        let install = try await runProcess(
            executable: "/bin/sh",
            arguments: [installer.path],
            directory: appSupport,
            streamOutput: true
        )
        guard install.code == 0 else { throw AppFailure("Impossible d’installer \(name).") }
    }

    private func ensureExternalAssistant(_ assistant: IDEChoice) async throws {
        let effective = assistant == .all ? IDEChoice.claude : assistant
        if try await commandExists(effective.commandName) { return }
        appendLog("Installation automatique de \(effective.title)…\n")
        switch effective {
        case .claude:
            try await installOfficialScript(url: "https://claude.ai/install.sh", name: "Claude Code")
        case .copilot:
            try await installOfficialScript(url: "https://gh.io/copilot-install", name: "GitHub Copilot")
        case .opencode:
            try await ensureOpenCode()
        case .cursor:
            try await installOfficialScript(url: "https://cursor.com/install", name: "Cursor Agent")
        case .gemini:
            try await ensureGemini()
        case .windsurf, .all:
            throw AppFailure("Cet assistant ne dispose pas encore d’une installation guidée sur Mac.")
        }
        guard try await commandExists(effective.commandName) else {
            throw AppFailure("\(effective.title) semble installé mais reste introuvable. Relancez l’application puis réessayez.")
        }
    }

    private func ensureGemini() async throws {
        try await ensurePortableNode()
        let npm = appSupport.appendingPathComponent("node-runtime/bin/npm")
        let destination = appSupport.appendingPathComponent("npm-tools", isDirectory: true)
        let result = try await runProcess(
            executable: npm.path,
            // `-g` : avec `--prefix`, la commande `gemini` va dans npm-tools/bin, le
            // dossier ajouté au PATH (sans `-g`, elle resterait dans node_modules/.bin).
            arguments: ["install", "-g", "--prefix", destination.path, "@google/gemini-cli"],
            directory: appSupport,
            streamOutput: true
        )
        guard result.code == 0 else { throw AppFailure("Impossible d’installer Gemini CLI.") }
    }

    private func ensurePortableNode() async throws {
        let node = appSupport.appendingPathComponent("node-runtime/bin/node")
        if fm.isExecutableFile(atPath: node.path) { return }
        appendLog("Préparation du composant nécessaire à Gemini…\n")
        let indexFile = appSupport.appendingPathComponent("node-releases.json")
        let archive = appSupport.appendingPathComponent("node-runtime.tar.gz")
        let stage = appSupport.appendingPathComponent("node-stage-\(UUID().uuidString)", isDirectory: true)
        defer {
            try? fm.removeItem(at: indexFile)
            try? fm.removeItem(at: archive)
            try? fm.removeItem(at: stage)
        }
        let indexDownload = try await runProcess(
            executable: "/usr/bin/curl",
            arguments: ["-fsSL", "https://nodejs.org/dist/index.json", "-o", indexFile.path],
            directory: appSupport,
            streamOutput: false
        )
        guard indexDownload.code == 0,
              let releases = try JSONSerialization.jsonObject(with: Data(contentsOf: indexFile)) as? [[String: Any]],
              let version = releases.first(where: { $0["lts"] is String })?["version"] as? String else {
            throw AppFailure("Impossible de déterminer la version stable de Node.js nécessaire à Gemini.")
        }
#if arch(arm64)
        let architecture = "arm64"
#else
        let architecture = "x64"
#endif
        let filename = "node-\(version)-darwin-\(architecture).tar.gz"
        let download = try await runProcess(
            executable: "/usr/bin/curl",
            arguments: ["-fsSL", "https://nodejs.org/dist/\(version)/\(filename)", "-o", archive.path],
            directory: appSupport,
            streamOutput: true
        )
        guard download.code == 0 else { throw AppFailure("Impossible de télécharger le composant nécessaire à Gemini.") }
        try fm.createDirectory(at: stage, withIntermediateDirectories: true)
        let extraction = try await runProcess(
            executable: "/usr/bin/tar",
            arguments: ["-xzf", archive.path, "--strip-components", "1", "-C", stage.path],
            directory: appSupport,
            streamOutput: false
        )
        guard extraction.code == 0, fm.isExecutableFile(atPath: stage.appendingPathComponent("bin/node").path) else {
            throw AppFailure("Impossible de préparer le composant nécessaire à Gemini.")
        }
        let runtime = appSupport.appendingPathComponent("node-runtime", isDirectory: true)
        try? fm.removeItem(at: runtime)
        try fm.moveItem(at: stage, to: runtime)
    }

    private func applyConfiguration(_ selected: SetupChoices) async throws {
        let answers: [String: Any] = [
            "coaching.style": selected.coachingStyle.rawValue,
            "coaching.intensity": selected.coachingIntensity.rawValue,
            "coaching.verbosity": selected.coachingVerbosity.rawValue,
            "sport.primary": selected.sport.rawValue,
            "sport.disciplines": selected.disciplines,
            "agents.enabled": selected.agents,
            "health.morning_check": selected.morningCheck.rawValue,
            "language.documents": selected.documentsLanguage,
            "language.responses": selected.responsesLanguage,
            "athlete.units": selected.units.rawValue
        ]
        let data = try JSONSerialization.data(withJSONObject: answers, options: [.prettyPrinted, .sortedKeys])
        let answerFile = appSupport.appendingPathComponent("setup-answers.json")
        try data.write(to: answerFile, options: .atomic)
        defer { try? fm.removeItem(at: answerFile) }

        let result = try await runProcess(
            executable: "/usr/bin/env",
            arguments: [
                "python3",
                engineURL.appendingPathComponent("scripts/coach_setup.py").path,
                "--workspace", selected.workspace,
                "--apply", answerFile.path
            ],
            directory: engineURL,
            streamOutput: true
        )
        guard result.code == 0 else { throw AppFailure("Vos préférences n’ont pas pu être enregistrées.") }
    }

    private func applyAthleteProfile(_ selected: SetupChoices) async throws {
        let candidates: [String: String] = [
            "Prénom / surnom": selected.firstName,
            "Année de naissance": selected.birthYear,
            "Années de pratique": selected.practiceYears,
            "Disponibilité hebdomadaire": selected.weeklyAvailability,
            "Jours impossibles": selected.impossibleDays,
            "Contraintes de vie": selected.lifeConstraints,
            "FC max": selected.maxHeartRate,
            "FC de repos de référence": selected.restingHeartRate,
            "FC au seuil": selected.thresholdHeartRate,
            "VO2max (Garmin)": selected.vo2Max,
            "Sexe": selected.sex,
            "Zones / seuils": selected.zones,
            "Allures de référence": selected.referencePaces,
            "Poids de forme": selected.usualWeight,
            "Besoin de sommeil": selected.sleepNeed,
            "Meilleures performances": selected.bestPerformances,
            "Antécédents de blessure": selected.injuryHistory,
            "Zones fragiles à surveiller": selected.fragileAreas,
            "Arrêts récents": selected.recentBreaks,
            "Lieu par défaut": selected.defaultLocation,
            "Créneau habituel": selected.usualSlot,
            "Terrain accessible": selected.accessibleTerrain,
            "Équipement": selected.equipment,
            "Home trainer": selected.homeTrainer,
            "Vélo sur home trainer": selected.homeTrainerBike,
            "Masse du vélo": selected.bikeMass,
            "FTP déclarée": selected.declaredFtp,
            "Sports croisés pratiqués": selected.disciplinesLabel,
            "Ce qui me motive": selected.motivation,
            "Ce qui ne marche pas avec moi": selected.coachingNoGo,
            "Sujets à ne pas commenter spontanément": selected.sensitiveTopics,
            "Tolérance au risque": selected.riskTolerance,
            "Quand me poser une question plutôt que supposer": selected.askBeforeAssuming
        ]
        let answers = candidates.compactMapValues { value -> String? in
            let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? nil : trimmed
        }
        guard !answers.isEmpty else { return }

        let data = try JSONSerialization.data(withJSONObject: answers, options: [.prettyPrinted, .sortedKeys])
        let answerFile = appSupport.appendingPathComponent("profile-answers.json")
        try data.write(to: answerFile, options: .atomic)
        defer { try? fm.removeItem(at: answerFile) }

        let result = try await runProcess(
            executable: "/usr/bin/env",
            arguments: [
                "python3",
                engineURL.appendingPathComponent("scripts/coach_setup.py").path,
                "--workspace", selected.workspace,
                "--apply-profile", answerFile.path
            ],
            directory: engineURL,
            streamOutput: true
        )
        guard result.code == 0 else { throw AppFailure("Votre profil d’athlète n’a pas pu être enregistré.") }
    }

    private func applyShoes(_ selected: SetupChoices) async throws {
        let shoes = selected.shoes.compactMap { shoe -> [String: String]? in
            let name = shoe.name.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !name.isEmpty else { return nil }
            return [
                "name": name,
                "start_date": shoe.purchaseDate.trimmingCharacters(in: .whitespacesAndNewlines),
                "threshold_km": shoe.thresholdKm.trimmingCharacters(in: .whitespacesAndNewlines),
                "start_km": shoe.startingKm.trimmingCharacters(in: .whitespacesAndNewlines),
                "usage": shoe.usage.trimmingCharacters(in: .whitespacesAndNewlines)
            ]
        }
        guard !shoes.isEmpty else { return }
        let data = try JSONSerialization.data(withJSONObject: shoes, options: [.prettyPrinted, .sortedKeys])
        let answerFile = appSupport.appendingPathComponent("shoe-answers.json")
        try data.write(to: answerFile, options: .atomic)
        defer { try? fm.removeItem(at: answerFile) }

        let result = try await runProcess(
            executable: "/usr/bin/env",
            arguments: [
                "python3",
                engineURL.appendingPathComponent("scripts/coach_setup.py").path,
                "--workspace", selected.workspace,
                "--apply-shoes", answerFile.path
            ],
            directory: engineURL,
            streamOutput: true
        )
        guard result.code == 0 else { throw AppFailure("Vos chaussures n’ont pas pu être enregistrées.") }
    }

    private func applyObjective(_ selected: SetupChoices) async throws {
        guard selected.hasObjective else { return }
        let candidates: [String: String] = [
            "Nom": selected.raceName,
            "Date": selected.raceDate,
            "Distance": selected.raceDistance,
            "Dénivelé positif": selected.raceElevation,
            "Lieu": selected.raceLocation,
            "Lien / trace GPX": selected.raceLink,
            "Objectif principal": selected.primaryGoal,
            "Temps visé": selected.targetTime,
            "Scénario acceptable / scénario noir": selected.acceptableScenario,
            "Semaines restantes": selected.weeksRemaining,
            "Volume hebdomadaire de départ": selected.startingVolume,
            "Volume hebdomadaire cible": selected.targetVolume,
            "Séances qualité par semaine": selected.qualitySessions,
            "Lieu d'entraînement par défaut": selected.defaultLocation,
            "Indisponibilités": selected.objectiveUnavailability,
            "Courses intermédiaires": selected.intermediateRaces,
            "Limites médicales en cours": selected.medicalLimits
        ]
        let answers = candidates.compactMapValues { value -> String? in
            let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? nil : trimmed
        }
        guard !answers.isEmpty else { return }
        let data = try JSONSerialization.data(withJSONObject: answers, options: [.prettyPrinted, .sortedKeys])
        let answerFile = appSupport.appendingPathComponent("objective-answers.json")
        try data.write(to: answerFile, options: .atomic)
        defer { try? fm.removeItem(at: answerFile) }

        let result = try await runProcess(
            executable: "/usr/bin/env",
            arguments: [
                "python3",
                engineURL.appendingPathComponent("scripts/coach_setup.py").path,
                "--workspace", selected.workspace,
                "--apply-objective", answerFile.path
            ],
            directory: engineURL,
            streamOutput: true
        )
        guard result.code == 0 else { throw AppFailure("Votre objectif n’a pas pu être enregistré.") }
    }

    func connectAccount() {
        let command: String
        if choices.source == .garmin {
            command = "cd \(shellQuote(engineURL.path)) && export PATH=\"$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH\" && uv run garmin-mcp-auth; printf '\\nConnexion terminée. Vous pouvez fermer cette fenêtre.\\n'; read -n 1"
        } else {
            let directory = fm.homeDirectoryForCurrentUser.appendingPathComponent(".config/ai-running-coach/intervals-icu-mcp")
            command = "mkdir -p \(shellQuote(directory.path)) && cd \(shellQuote(directory.path)) && export PATH=\"$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH\" && intervals-icu-mcp-auth; printf '\\nConnexion terminée. Vous pouvez fermer cette fenêtre.\\n'; read -n 1"
        }
        let escaped = command.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
        let script = "tell application \"Terminal\" to do script \"\(escaped)\"\ntell application \"Terminal\" to activate"
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", script]
        try? process.run()
    }

    /// Connexion de l'abonnement (ChatGPT : adresse + code d'appareil ; Copilot : code GitHub) dans une
    /// fenêtre Terminal, comme « Connecter mon compte » : `arc_llm.py login chatgpt|copilot`. Le jeton
    /// reste dans le magasin d'OpenCode du coach ; l'application ne le lit jamais.
    func connectSubscription() {
        guard let provider = savedChatProvider else { return }
        let home = fm.homeDirectoryForCurrentUser.path
        // Comme pour Garmin : nos dossiers sont AJOUTÉS devant le PATH de l'utilisateur (jamais à sa place).
        let extra = [
            "\(home)/.local/bin",
            "\(home)/.opencode/bin",
            appSupport.appendingPathComponent("node-runtime/bin").path,
            appSupport.appendingPathComponent("npm-tools/bin").path,
            "/opt/homebrew/bin", "/usr/local/bin"
        ].joined(separator: ":")
        let login = "python3 \(shellQuote(engineURL.appendingPathComponent("scripts/arc_llm.py").path)) login \(provider.llmID) --data-dir \(shellQuote(coachOpenCodeStore.path))"
        let command = "cd \(shellQuote(engineURL.path)) && export PATH=\(shellQuote(extra)):\"$PATH\" && clear && \(login); printf '\\nVous pouvez fermer cette fenêtre.\\n'; read -n 1"
        let escaped = command.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
        let script = "tell application \"Terminal\" to do script \"\(escaped)\"\ntell application \"Terminal\" to activate"
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", script]
        try? process.run()
        // Rend l'état de la connexion observable : le jeton arrive pendant que l'athlète valide dans
        // son navigateur, sans que l'application change de premier plan. On sonde jusqu'à 10 minutes.
        subscriptionPoll?.cancel()
        subscriptionPoll = Task { @MainActor in
            for _ in 0..<200 {
                if Task.isCancelled { return }
                try? await Task.sleep(nanoseconds: 3_000_000_000)
                self.objectWillChange.send()
                if self.subscriptionConnected { break }
            }
        }
    }

    func synchronizeNow() {
        guard !manualSyncRunning else { return }
        guard isAuthenticated else {
            manualSyncFailed = true
            manualSyncStatus = "Connectez d’abord \(choices.source.title)."
            return
        }
        manualSyncRunning = true
        manualSyncFailed = false
        manualSyncStatus = "Synchronisation en cours…"
        Task {
            do {
                let result = try await runProcess(
                    executable: "/usr/bin/env",
                    arguments: [
                        "ARC_WORKSPACE=\(workspaceURL.path)",
                        engineURL.appendingPathComponent("scripts/daily-sync.sh").path
                    ],
                    directory: engineURL,
                    streamOutput: false
                )
                let output = result.output
                if output.localizedCaseInsensitiveContains("déjà en cours") {
                    manualSyncStatus = "Une synchronisation est déjà en cours."
                } else if output.localizedCaseInsensitiveContains("budget quotidien atteint") {
                    manualSyncStatus = "Synchronisation reportée : plafond quotidien atteint."
                } else if result.code == 0 && !output.localizedCaseInsensitiveContains("ERREUR :") {
                    manualSyncStatus = "Synchronisation terminée — les données sont à jour."
                } else {
                    manualSyncFailed = true
                    manualSyncStatus = "La synchronisation demande votre attention. Vérifiez les connexions ou le diagnostic."
                }
            } catch {
                manualSyncFailed = true
                manualSyncStatus = "Impossible de lancer la synchronisation : \(error.localizedDescription)"
            }
            manualSyncRunning = false
        }
    }

    func launchExternalCoach() {
        let assistant = choices.ide == .all ? IDEChoice.claude : choices.ide
        let home = fm.homeDirectoryForCurrentUser.path
        let path = [
            "\(home)/.local/bin",
            "\(home)/.opencode/bin",
            "\(home)/.claude/bin",
            appSupport.appendingPathComponent("node-runtime/bin").path,
            appSupport.appendingPathComponent("npm-tools/bin").path,
            "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"
        ].joined(separator: ":")
        let guidance = "Bienvenue dans votre espace de coaching. Au premier lancement, suivez simplement l’écran pour vous connecter, puis écrivez votre demande au coach."
        let command = "cd \(shellQuote(workspaceURL.path)) && export PATH=\(shellQuote(path)) && clear && printf '\\n%s\\n\\n' \(shellQuote(guidance)) && exec \(assistant.commandName)"
        let escaped = command.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
        let script = "tell application \"Terminal\" to do script \"\(escaped)\"\ntell application \"Terminal\" to activate"
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", script]
        do {
            try process.run()
        } catch {
            errorMessage = "Impossible d’ouvrir \(assistant.title) : \(error.localizedDescription)"
            phase = .failed
        }
    }

    func launchDashboard(openChat: Bool = false) {
        if dashboardProcess?.isRunning == true {
            if let base = dashboardBaseURL {
                NSWorkspace.shared.open(openChat ? base.appendingPathComponent("chat.html") : base)
            }
            return
        }
        log = ""
        dashboardBaseURL = nil
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [engineURL.appendingPathComponent("scripts/dashboard.sh").path, "--no-open"]
        process.currentDirectoryURL = engineURL
        process.environment = processEnvironment(workspace: workspaceURL.path)
        process.standardOutput = pipe
        process.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            Task { @MainActor in
                self?.appendLog(text)
                if let range = text.range(of: "URL: ") {
                    let suffix = text[range.upperBound...]
                    let value = suffix.split(whereSeparator: { $0 == "\n" || $0 == "\r" }).first.map(String.init) ?? ""
                    if let url = URL(string: value) {
                        self?.dashboardBaseURL = url
                        NSWorkspace.shared.open(openChat ? url.appendingPathComponent("chat.html") : url)
                    }
                }
            }
        }
        process.terminationHandler = { [weak self] _ in
            Task { @MainActor in
                self?.dashboardRunning = false
                self?.dashboardBaseURL = nil
            }
        }
        do {
            try process.run()
            dashboardProcess = process
            dashboardRunning = true
        } catch {
            errorMessage = "Le tableau de bord n’a pas pu démarrer : \(error.localizedDescription)"
            phase = .failed
        }
    }

    func stopDashboard() {
        dashboardProcess?.terminate()
        dashboardProcess = nil
        dashboardBaseURL = nil
        dashboardRunning = false
    }

    func openWorkspace() { NSWorkspace.shared.open(workspaceURL) }

    func runDiagnostics() {
        diagnostics = "Vérification en cours…"
        showDiagnostics = true
        Task {
            do {
                let result = try await runProcess(
                    executable: "/usr/bin/env",
                    arguments: ["python3", engineURL.appendingPathComponent("scripts/coach_doctor.py").path, "--workspace", workspaceURL.path],
                    directory: engineURL,
                    streamOutput: false
                )
                diagnostics = result.output.isEmpty ? "Diagnostic terminé (code \(result.code))." : result.output
            } catch {
                diagnostics = "Diagnostic impossible : \(error.localizedDescription)"
            }
        }
    }

    func retryLastOperation() {
        wasUpdating ? updateEngine() : install()
    }

    func leaveFailure() {
        phase = wasUpdating && isInstalled ? .ready : .welcome
        progress = 0
        progressTitle = "Préparation"
    }

    private func appendLog(_ text: String) {
        log.append(text)
        if log.count > 24_000 { log.removeFirst(log.count - 24_000) }
    }

    private func processEnvironment(workspace: String? = nil) -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        let home = fm.homeDirectoryForCurrentUser.path
        env["PATH"] = "\(home)/.local/bin:\(home)/.opencode/bin:\(home)/.claude/bin:\(appSupport.path)/node-runtime/bin:\(appSupport.path)/npm-tools/bin:\(home)/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
        env["HOME"] = home
        if let workspace { env["ARC_WORKSPACE"] = workspace }
        return env
    }

    private func runProcess(
        executable: String,
        arguments: [String],
        directory: URL,
        streamOutput: Bool
    ) async throws -> ProcessResult {
        try await withCheckedThrowingContinuation { continuation in
            let process = Process()
            let pipe = Pipe()
            let buffer = OutputBuffer()
            process.executableURL = URL(fileURLWithPath: executable)
            process.arguments = arguments
            process.currentDirectoryURL = directory
            process.environment = processEnvironment()
            process.standardOutput = pipe
            process.standardError = pipe

            pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let data = handle.availableData
                guard !data.isEmpty else { return }
                buffer.append(data)
                if streamOutput, let text = String(data: data, encoding: .utf8) {
                    Task { @MainActor in self?.appendLog(text) }
                }
            }
            process.terminationHandler = { process in
                pipe.fileHandleForReading.readabilityHandler = nil
                let tail = pipe.fileHandleForReading.readDataToEndOfFile()
                buffer.append(tail)
                if streamOutput && !tail.isEmpty, let tailText = String(data: tail, encoding: .utf8) {
                    Task { @MainActor in self.appendLog(tailText) }
                }
                continuation.resume(returning: ProcessResult(code: process.terminationStatus, output: buffer.string()))
            }
            do { try process.run() }
            catch { continuation.resume(throwing: error) }
        }
    }

    private func shellQuote(_ value: String) -> String {
        "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }
}

struct AppFailure: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

struct BrandHeader: View {
    var subtitle: String
    var body: some View {
        HStack(spacing: 18) {
            Image(nsImage: NSApplication.shared.applicationIconImage)
                .resizable()
                .interpolation(.high)
                .scaledToFit()
                .frame(width: 72, height: 72)
            VStack(alignment: .leading, spacing: 4) {
                Text("AI Running Coach").font(.system(size: 28, weight: .bold))
                Text(subtitle).foregroundStyle(.secondary)
            }
            Spacer()
        }
    }
}

struct SetupView: View {
    @ObservedObject var model: CoachAppModel
    var enrichment = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                BrandHeader(subtitle: enrichment ? "Compléter votre profil et votre objectif" : "Votre coach de course, installé sans ligne de commande")
                Text(enrichment
                     ? "Ajoutez ce qui manque aujourd’hui. Les informations déjà enregistrées sont conservées."
                     : "Quelques choix suffisent. L’application installe le moteur, prépare votre espace personnel et reste ensuite votre point d’entrée.")
                    .font(.title3).foregroundStyle(.secondary)

                GroupBox("1. Faisons connaissance") {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Ces informations permettent au coach d’adapter la charge à votre expérience et à votre vraie semaine.")
                            .font(.callout).foregroundStyle(.secondary)
                        Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 10) {
                            GridRow {
                                Text("Prénom ou surnom")
                                TextField("Camille", text: $model.choices.firstName)
                            }
                            GridRow {
                                Text("Année de naissance")
                                TextField("1988", text: $model.choices.birthYear)
                            }
                            GridRow {
                                Text("Années de pratique")
                                TextField("5 ans", text: $model.choices.practiceYears)
                            }
                            GridRow {
                                Text("Temps disponible")
                                TextField("4 séances, environ 6 h par semaine", text: $model.choices.weeklyAvailability)
                            }
                            GridRow {
                                Text("Ville habituelle")
                                TextField("Annecy", text: $model.choices.defaultLocation)
                            }
                        }

                        DisclosureGroup("Compléter le profil maintenant", isExpanded: $model.showOptionalProfile) {
                            VStack(alignment: .leading, spacing: 10) {
                                ProfileField(label: "Jours impossibles", placeholder: "Mardi et dimanche matin", text: $model.choices.impossibleDays)
                                ProfileField(label: "Contraintes de vie", placeholder: "Travail, famille, déplacements…", text: $model.choices.lifeConstraints)
                                ProfileField(label: "Créneau habituel", placeholder: "Pause de midi, tôt le matin, soir…", text: $model.choices.usualSlot)
                                ProfileField(label: "Terrain accessible", placeholder: "Forêt, piste, côtes, salle…", text: $model.choices.accessibleTerrain)
                                ProfileField(label: "Équipement disponible", placeholder: "Home trainer, haltères, tapis…", text: $model.choices.equipment)
                                ProfileField(label: "Home trainer", placeholder: "Wahoo KICKR…", text: $model.choices.homeTrainer)
                                ProfileField(label: "Vélo sur home trainer", placeholder: "Vélo de route…", text: $model.choices.homeTrainerBike)
                                ProfileField(label: "Masse du vélo", placeholder: "8,5 kg", text: $model.choices.bikeMass)
                                ProfileField(label: "FTP déclarée", placeholder: "230 W, issue d'un vrai test", text: $model.choices.declaredFtp)
                                Divider()
                                Text("Physiologie — laissez vide ce que vous ne connaissez pas").font(.headline)
                                ProfileField(label: "FC max", placeholder: "182 bpm", text: $model.choices.maxHeartRate)
                                ProfileField(label: "FC de repos", placeholder: "47 bpm, valeur habituelle", text: $model.choices.restingHeartRate)
                                ProfileField(label: "FC au seuil", placeholder: "170 bpm", text: $model.choices.thresholdHeartRate)
                                ProfileField(label: "VO2max Garmin", placeholder: "52 ml/kg/min", text: $model.choices.vo2Max)
                                ProfileField(label: "Sexe", placeholder: "Facultatif — F ou H", text: $model.choices.sex)
                                ProfileField(label: "Zones / seuils", placeholder: "Z1 120–135, Z2 136–150…", text: $model.choices.zones)
                                ProfileField(label: "Allures de référence", placeholder: "10 km en 45 min, semi en 1 h 40…", text: $model.choices.referencePaces)
                                ProfileField(label: "Poids de forme", placeholder: "68 kg", text: $model.choices.usualWeight)
                                ProfileField(label: "Besoin de sommeil", placeholder: "7 h 30", text: $model.choices.sleepNeed)
                                Divider()
                                Text("Santé et relation avec le coach").font(.headline)
                                ProfileField(label: "Meilleures performances", placeholder: "Marathon 3 h 35, trail 50 km…", text: $model.choices.bestPerformances)
                                ProfileField(label: "Blessures passées", placeholder: "Entorse droite en 2024…", text: $model.choices.injuryHistory)
                                ProfileField(label: "Zones fragiles", placeholder: "Tendon d’Achille gauche…", text: $model.choices.fragileAreas)
                                ProfileField(label: "Arrêts récents", placeholder: "Maladie, coupure ou reprise…", text: $model.choices.recentBreaks)
                                ProfileField(label: "Ce qui me motive", placeholder: "La régularité, les chiffres, le plaisir…", text: $model.choices.motivation)
                                ProfileField(label: "Ce qui ne marche pas", placeholder: "La culpabilisation, trop de détails…", text: $model.choices.coachingNoGo)
                                ProfileField(label: "Sujets sensibles", placeholder: "Le poids, sauf si je le demande…", text: $model.choices.sensitiveTopics)
                                ProfileField(label: "Tolérance au risque", placeholder: "Prudent, équilibré ou agressif — et pourquoi", text: $model.choices.riskTolerance)
                                ProfileField(label: "Me demander avant de supposer", placeholder: "Douleur, disponibilité, changement d’objectif…", text: $model.choices.askBeforeAssuming)
                                Divider()
                                Text("Sports croisés pratiqués").font(.headline)
                                Text("Le coach ne programmera que les activités sélectionnées.")
                                    .font(.caption).foregroundStyle(.secondary)
                                Grid(alignment: .leading, horizontalSpacing: 28, verticalSpacing: 8) {
                                    GridRow {
                                        Toggle("Vélo", isOn: $model.choices.crossCycling)
                                        Toggle("Natation", isOn: $model.choices.crossSwimming)
                                    }
                                    GridRow {
                                        Toggle("Renforcement", isOn: $model.choices.crossStrength)
                                        Toggle("Randonnée", isOn: $model.choices.crossHiking)
                                    }
                                    GridRow {
                                        Toggle("Elliptique", isOn: $model.choices.crossElliptical)
                                        Toggle("Rameur", isOn: $model.choices.crossRowing)
                                    }
                                }
                                Divider()
                                Text("Chaussures").font(.headline)
                                Text("La première paire renseignée devient la paire utilisée par défaut quand une séance n’en précise aucune.")
                                    .font(.caption).foregroundStyle(.secondary)
                                ForEach(model.choices.shoes.indices, id: \.self) { index in
                                    GroupBox("Paire \(index + 1)") {
                                        VStack(alignment: .leading, spacing: 8) {
                                            ProfileField(label: "Nom / modèle", placeholder: "Hoka Speedgoat 6", text: $model.choices.shoes[index].name)
                                            ProfileField(label: "Date d’achat", placeholder: "2026-09-01 ou septembre 2026", text: $model.choices.shoes[index].purchaseDate)
                                            ProfileField(label: "Alerte d’usure", placeholder: "700", text: $model.choices.shoes[index].thresholdKm)
                                            ProfileField(label: "Kilométrage actuel", placeholder: "0", text: $model.choices.shoes[index].startingKm)
                                            ProfileField(label: "Usage", placeholder: "trail, route, compétition, récup…", text: $model.choices.shoes[index].usage)
                                            if model.choices.shoes.count > 1 {
                                                HStack {
                                                    Spacer()
                                                    Button("Retirer cette paire", role: .destructive) {
                                                        model.choices.shoes.remove(at: index)
                                                    }
                                                }
                                            }
                                        }.padding(6)
                                    }
                                }
                                Button {
                                    model.choices.shoes.append(ShoeChoice())
                                } label: {
                                    Label("Ajouter une paire", systemImage: "plus.circle")
                                }
                            }.padding(.top, 8)
                        }
                        Text(enrichment
                             ? "Vous pouvez ne remplir que les nouveaux éléments utiles aujourd’hui."
                             : "Les cinq premiers champs sont nécessaires. Le reste pourra être complété plus tard avec le coach.")
                            .font(.caption).foregroundStyle(.secondary)
                    }.padding(8)
                }

                GroupBox("2. Votre objectif") {
                    VStack(alignment: .leading, spacing: 12) {
                        Toggle("J’ai déjà une course ou un objectif précis", isOn: $model.choices.hasObjective)
                        if model.choices.hasObjective {
                            Text("Les quatre premiers champs permettent au coach de construire un plan cohérent. Les autres affinent la stratégie.")
                                .font(.callout).foregroundStyle(.secondary)
                            ProfileField(label: "Nom de la course", placeholder: "Trail des Crêtes", text: $model.choices.raceName)
                            ProfileField(label: "Date", placeholder: "2027-06-12", text: $model.choices.raceDate)
                            ProfileField(label: "Distance", placeholder: "52 km", text: $model.choices.raceDistance)
                            ProfileField(label: "Objectif principal", placeholder: "Finir sereinement, temps cible…", text: $model.choices.primaryGoal)
                            DisclosureGroup("Ajouter les détails de l’objectif") {
                                VStack(alignment: .leading, spacing: 10) {
                                    ProfileField(label: "Dénivelé positif", placeholder: "3 200 m", text: $model.choices.raceElevation)
                                    ProfileField(label: "Lieu", placeholder: "Chamonix", text: $model.choices.raceLocation)
                                    ProfileField(label: "Lien ou trace GPX", placeholder: "https://… ou chemin du fichier", text: $model.choices.raceLink)
                                    ProfileField(label: "Temps visé", placeholder: "7 h 30", text: $model.choices.targetTime)
                                    ProfileField(label: "Scénarios", placeholder: "Acceptable : finir ; noir : douleur…", text: $model.choices.acceptableScenario)
                                    ProfileField(label: "Semaines restantes", placeholder: "24", text: $model.choices.weeksRemaining)
                                    ProfileField(label: "Volume actuel", placeholder: "45 km / 6 h", text: $model.choices.startingVolume)
                                    ProfileField(label: "Volume cible", placeholder: "70 km / 9 h", text: $model.choices.targetVolume)
                                    ProfileField(label: "Séances qualité", placeholder: "2 par semaine", text: $model.choices.qualitySessions)
                                    ProfileField(label: "Indisponibilités", placeholder: "Vacances du 10 au 17 avril…", text: $model.choices.objectiveUnavailability)
                                    ProfileField(label: "Courses intermédiaires", placeholder: "Semi le 15 mars…", text: $model.choices.intermediateRaces)
                                    ProfileField(label: "Limites médicales", placeholder: "Aucune, ou consignes en cours", text: $model.choices.medicalLimits)
                                }.padding(.top, 8)
                            }
                        } else {
                            Text("Aucun problème : votre première discussion pourra servir à choisir une course ou à définir un objectif de progression.")
                                .font(.callout).foregroundStyle(.secondary)
                        }
                    }.padding(8)
                }

                if !enrichment {
                GroupBox("3. Vos données sportives") {
                    VStack(alignment: .leading, spacing: 12) {
                        Picker("Source", selection: $model.choices.source) {
                            ForEach(DataSource.allCases) { Text($0.title).tag($0) }
                        }.pickerStyle(.segmented)
                        Text(model.choices.source.detail).font(.callout).foregroundStyle(.secondary)
                    }.padding(8)
                }

                GroupBox("4. Votre pratique") {
                    VStack(alignment: .leading, spacing: 12) {
                        Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 12) {
                            GridRow { Text("Discipline"); Picker("", selection: $model.choices.sport) { ForEach(SportChoice.allCases) { Text($0.title).tag($0) } }.labelsHidden() }
                            GridRow { Text("Style du coach"); Picker("", selection: $model.choices.coachingStyle) { ForEach(CoachingStyle.allCases) { Text($0.title).tag($0) } }.labelsHidden() }
                            GridRow { Text("Fermeté"); Picker("", selection: $model.choices.coachingIntensity) { ForEach(CoachingIntensity.allCases) { Text($0.title).tag($0) } }.labelsHidden() }
                            GridRow { Text("Longueur des retours"); Picker("", selection: $model.choices.coachingVerbosity) { ForEach(CoachingVerbosity.allCases) { Text($0.title).tag($0) } }.labelsHidden() }
                            GridRow { Text("Bilan du matin"); Picker("", selection: $model.choices.morningCheck) { ForEach(MorningCheck.allCases) { Text($0.title).tag($0) } }.labelsHidden() }
                            GridRow { Text("Unités"); Picker("", selection: $model.choices.units) { ForEach(UnitChoice.allCases) { Text($0.title).tag($0) } }.labelsHidden() }
                        }
                        DisclosureGroup("Langues des documents et des réponses") {
                            VStack(alignment: .leading, spacing: 10) {
                                ProfileField(label: "Documents", placeholder: "fr", text: $model.choices.documentsLanguage)
                                ProfileField(label: "Réponses", placeholder: "auto", text: $model.choices.responsesLanguage)
                                Text("Utilisez un code court comme fr, en ou nl. « auto » répond dans la langue de votre message.")
                                    .font(.caption).foregroundStyle(.secondary)
                            }.padding(.top, 8)
                        }
                    }.padding(8)
                }

                GroupBox("5. Votre équipe") {
                    VStack(alignment: .leading, spacing: 10) {
                        Label("Coach — toujours inclus", systemImage: "checkmark.circle.fill")
                        Toggle("Suivi santé et récupération", isOn: $model.choices.medical)
                        Toggle("Nutrition et ravitaillement", isOn: $model.choices.nutritionist)
                        Toggle("Stratégie de course et analyse GPX", isOn: $model.choices.strategist)
                    }.padding(8)
                }

                GroupBox("6. Comment parler au coach") {
                    VStack(alignment: .leading, spacing: 12) {
                        Picker("Mode", selection: $model.choices.chatChoice) {
                            ForEach(ChatChoice.allCases) { Text($0.title).tag($0) }
                        }
                        .pickerStyle(.segmented)
                        if model.choices.chatChoice == .integrated {
                            Picker("Fournisseur", selection: $model.choices.chatProvider) {
                                ForEach(ChatProvider.allCases) { Text($0.title).tag($0) }
                            }
                            .pickerStyle(.segmented)
                        }
                        if model.choices.chatChoice == .integrated && model.choices.chatProvider.isSubscription {
                            Text("Vous retrouverez un bouton « Parler au coach » dans l’application. Aucune clé API : le chat et la synchronisation automatique utilisent votre abonnement \(model.choices.chatProvider.planName). Une fenêtre Terminal s’ouvre à la fin de l’installation pour vous connecter avec votre compte.")
                                .font(.callout).foregroundStyle(.secondary)
                            Text(model.choices.chatProvider == .chatGPT
                                 ? "Forfaits acceptés : ChatGPT Plus ou Pro (l’offre Free est refusée par OpenAI). Aucun coût supplémentaire : les limites de votre forfait s’appliquent, et la synchronisation quotidienne les consomme aussi. Les modèles par défaut n’ont pas été évalués sur un vrai forfait."
                                 : "Forfaits acceptés : Copilot Pro, Pro+, Business ou Enterprise (Copilot Free n’est pas pris en charge). Aucun coût supplémentaire : les crédits de votre forfait s’appliquent, et la synchronisation quotidienne les consomme aussi. Les modèles par défaut n’ont pas été évalués sur un vrai forfait.")
                                .font(.callout)
                            Toggle("Synchroniser aussi avec mon forfait (une ou deux fois par jour)", isOn: $model.choices.syncWithSubscription)
                            Text(model.choices.syncWithSubscription
                                 ? "La synchronisation automatique de vos données sportives utilisera aussi votre forfait \(model.choices.chatProvider.planName), sur vos limites. Dans ce mode, l’application n’a pas d’autre exécuteur de synchronisation. Aucune déclaration officielle n’autorise l’usage planifié sans surveillance d’un forfait grand public : vérifiez les conditions de votre fournisseur."
                                 : "Sans cette option, la synchronisation automatique n’est pas installée : lancez « Synchroniser maintenant » quand vous le souhaitez.")
                                .font(.caption).foregroundStyle(.secondary)
                            Text("Vos échanges avec le coach passent par votre compte \(model.choices.chatProvider.planName) : ses réglages de confidentialité s’appliquent.")
                                .font(.caption).foregroundStyle(.secondary)
                        } else if model.choices.chatChoice == .integrated {
                            Text("Vous retrouverez un bouton « Parler au coach » dans l’application. Ce chat utilise OpenRouter, facturé à l’usage ; votre plafond quotidien évite les surprises. La synchronisation automatique des données sportives sera également activée.")
                                .font(.callout).foregroundStyle(.secondary)
                            Picker("OpenRouter", selection: $model.choices.openRouterAccess) {
                                ForEach(OpenRouterAccess.allCases) { Text($0.title).tag($0) }
                            }
                            .pickerStyle(.segmented)
                            if model.choices.openRouterAccess == .connect {
                                Text("Au moment de l’installation, une page OpenRouter s’ouvre : créez un compte ou connectez-vous, puis autorisez le coach. Aucune clé à copier.")
                                    .font(.callout).foregroundStyle(.secondary)
                                Text("Coût : environ 1 € par mois. Conseil : achetez 10 $ de crédit une fois, ce qui couvre environ un an de coaching.")
                                    .font(.callout)
                            } else {
                                HStack {
                                    Text("Clé OpenRouter").frame(width: 170, alignment: .leading)
                                    SecureField("sk-or-v1-…", text: $model.choices.openRouterAPIKey)
                                    Link("Créer une clé", destination: URL(string: "https://openrouter.ai/settings/keys")!)
                                }
                            }
                            ProfileField(label: "Plafond par jour", placeholder: "1.00", text: $model.choices.chatBudget)
                            Text("La clé est enregistrée uniquement sur ce Mac dans un fichier privé. Les données de la conversation sont envoyées au fournisseur du modèle choisi.")
                                .font(.caption).foregroundStyle(.secondary)
                            Link("Santé : refuser les fournisseurs qui entraînent sur vos données (confidentialité OpenRouter)",
                                 destination: URL(string: "https://openrouter.ai/settings/privacy")!)
                                .font(.caption)
                        } else {
                            Picker("Assistant IA", selection: $model.choices.ide) {
                                ForEach(IDEChoice.guidedCases) { Text($0.title).tag($0) }
                            }
                            if model.choices.ide == .gemini {
                                Text("Gemini CLI a été remplacé par Antigravity CLI pour les comptes Google non payants (18 juin 2026). Il reste utilisable avec une clé API Gemini (palier gratuit : 250 requêtes par jour, Flash ; ces données peuvent être utilisées par Google, à éviter pour la santé) ou avec une licence payante.")
                                    .font(.caption).foregroundStyle(.orange)
                            }
                            Text("L’application installe automatiquement l’assistant choisi. Ensuite, le bouton « Parler au coach » ouvre le bon dossier et lance l’assistant ; sa connexion s’affiche simplement au premier lancement.")
                                .font(.caption).foregroundStyle(.secondary)
                            Text("Après sa connexion initiale, le même assistant synchronisera automatiquement vos données en arrière-plan ; vous n’aurez pas à l’ouvrir pour cela.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }.padding(8)
                }

                GroupBox("7. Où garder vos données") {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            TextField("Dossier de vos données", text: $model.choices.workspace)
                            Button("Choisir…") { model.chooseWorkspace() }
                        }
                        Text("Vos séances et plans restent dans ce dossier. Ils ne sont jamais placés dans l’application.")
                            .font(.caption).foregroundStyle(.secondary)
                    }.padding(8)
                }
                }

                HStack {
                    if enrichment {
                        Button("Annuler") { model.showEnrichment = false }
                    }
                    Spacer()
                    Button(enrichment ? "Enregistrer les compléments" : "Installer mon coach") {
                        enrichment ? model.saveEnrichment() : model.install()
                    }
                        .buttonStyle(.borderedProminent).controlSize(.large)
                        .disabled(
                            model.enrichmentSaving
                            || (!enrichment && (
                                model.choices.workspace.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                || !model.choices.profileIsCompleteEnough
                                || !model.choices.objectiveIsCompleteEnough
                                || !model.choices.chatIsCompleteEnough
                            ))
                        )
                }
                if enrichment && !model.enrichmentError.isEmpty {
                    Label(model.enrichmentError, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                }
            }.padding(28).frame(maxWidth: 760)
        }
    }
}

struct ProfileField: View {
    var label: String
    var placeholder: String
    @Binding var text: String
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 16) {
            Text(label).frame(width: 170, alignment: .leading)
            TextField(placeholder, text: $text)
        }
    }
}

struct InstallingView: View {
    @ObservedObject var model: CoachAppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            BrandHeader(subtitle: "Installation en cours")
            VStack(alignment: .leading, spacing: 8) {
                Text(model.progressTitle).font(.headline)
                ProgressView(value: model.progress)
                Text("Gardez cette fenêtre ouverte. La première installation peut prendre quelques minutes.")
                    .font(.callout).foregroundStyle(.secondary)
                if model.connecting {
                    HStack(spacing: 12) {
                        ProgressView().controlSize(.small)
                        Text("En attente de l’autorisation dans votre navigateur…")
                        Button("Annuler la connexion") { model.cancelConnection() }
                    }
                    if let url = model.connectURL {
                        Link("Le navigateur ne s’est pas ouvert ? Ouvrir la page d’autorisation OpenRouter", destination: url)
                    }
                }
            }
            ScrollView {
                Text(model.log.isEmpty ? "Préparation…" : model.log)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
            }.padding(12).background(.black.opacity(0.82)).foregroundStyle(.white.opacity(0.9)).clipShape(RoundedRectangle(cornerRadius: 10))
        }.padding(28)
    }
}

struct ReadyView: View {
    @ObservedObject var model: CoachAppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            BrandHeader(subtitle: "Tout est prêt pour courir")

            HStack(spacing: 14) {
                StatusCard(
                    title: model.isAuthenticated ? "Compte connecté" : "Compte à connecter",
                    detail: model.isAuthenticated ? model.choices.source.title : "Une dernière étape sécurisée",
                    icon: model.isAuthenticated ? "checkmark.shield.fill" : "person.crop.circle.badge.exclamationmark",
                    color: model.isAuthenticated ? .green : .orange
                )
                StatusCard(title: "Données personnelles", detail: model.workspaceURL.lastPathComponent, icon: "folder.fill", color: .blue)
                StatusCard(
                    title: "Synchronisation",
                    detail: model.syncStatusDetail,
                    icon: "arrow.triangle.2.circlepath",
                    color: .purple
                )
            }

            if !model.isAuthenticated {
                GroupBox {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Connectez \(model.choices.source.title)").font(.headline)
                            Text("Une fenêtre sécurisée s’ouvre uniquement pour la connexion et le code MFA éventuel.")
                                .font(.callout).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("Connecter mon compte") { model.connectAccount() }.buttonStyle(.borderedProminent)
                    }.padding(8)
                }
            }

            if let plan = model.savedChatProvider, !model.subscriptionConnected {
                GroupBox {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Connectez \(plan.planName)").font(.headline)
                            Text("Une fenêtre Terminal affiche une adresse et un code à valider dans votre navigateur. Le chat et la synchronisation utilisent ensuite votre abonnement, sans clé API.")
                                .font(.callout).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("Connecter \(plan.planName)") { model.connectSubscription() }.buttonStyle(.borderedProminent)
                    }.padding(8)
                }
            }

            if model.updateAvailable {
                GroupBox {
                    HStack {
                        Label(model.updateWaiting ? "Le moteur sera mis à jour après la synchronisation en cours." : "Une nouvelle version du moteur est incluse dans l’application.", systemImage: "arrow.down.circle.fill")
                        Spacer()
                        Button("Mettre à jour") { model.updateEngine() }.buttonStyle(.borderedProminent)
                    }.padding(8)
                }
            }

            if model.integratedChatPending {
                GroupBox {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Label("Le chat n’est pas encore connecté", systemImage: "exclamationmark.triangle.fill")
                                .foregroundStyle(.orange)
                            Text("Le chat et la synchronisation automatique de vos données attendent la connexion à OpenRouter. Environ 1 € par mois.")
                                .font(.callout).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("Connecter OpenRouter") { model.connectChatLater() }.buttonStyle(.borderedProminent)
                    }.padding(8)
                }
            }

            HStack(spacing: 12) {
                if model.integratedChatPending {
                    Button {
                        model.launchDashboard()
                    } label: {
                        Label("Tableau de bord", systemImage: "chart.line.uptrend.xyaxis")
                    }.buttonStyle(.borderedProminent).controlSize(.large)
                } else if model.integratedChatEnabled {
                    Button {
                        model.launchDashboard(openChat: true)
                    } label: {
                        Label("Parler au coach", systemImage: "bubble.left.and.bubble.right.fill")
                    }.buttonStyle(.borderedProminent).controlSize(.large)

                    Button {
                        model.launchDashboard()
                    } label: {
                        Label("Tableau de bord", systemImage: "chart.line.uptrend.xyaxis")
                    }.controlSize(.large)
                } else {
                    Button {
                        model.launchExternalCoach()
                    } label: {
                        Label("Parler au coach avec \(model.externalAssistantTitle)", systemImage: "bubble.left.and.bubble.right.fill")
                    }.buttonStyle(.borderedProminent).controlSize(.large)

                    Button {
                        model.launchDashboard()
                    } label: {
                        Label("Tableau de bord", systemImage: "chart.line.uptrend.xyaxis")
                    }.controlSize(.large)
                }

                if model.dashboardRunning {
                    Button("Arrêter") { model.stopDashboard() }.controlSize(.large)
                }
                Button { model.openWorkspace() } label: { Label("Mes données", systemImage: "folder") }.controlSize(.large)
            }

            HStack(spacing: 12) {
                Button {
                    model.synchronizeNow()
                } label: {
                    HStack(spacing: 6) {
                        if model.manualSyncRunning {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "arrow.triangle.2.circlepath")
                        }
                        Text(model.manualSyncRunning ? "Synchronisation…" : "Synchroniser maintenant")
                    }
                }
                .disabled(!model.isAuthenticated || model.manualSyncRunning)
                .controlSize(.large)
                if !model.manualSyncStatus.isEmpty {
                    Text(model.manualSyncStatus)
                        .font(.callout)
                        .foregroundStyle(model.manualSyncFailed ? Color.red : Color.secondary)
                }
                Spacer()
            }

            Divider()
            HStack {
                Button("Vérifier l’installation") { model.runDiagnostics() }
                Button(model.enrichmentLoading ? "Chargement du profil…" : "Compléter mon profil et mon objectif") {
                    model.openEnrichment()
                }
                .disabled(model.enrichmentLoading)
                if model.isAuthenticated {
                    Button("Reconnecter le compte") { model.connectAccount() }
                }
                Spacer()
                Text(model.workspaceURL.path).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
        }
        .padding(28)
        .sheet(isPresented: $model.showDiagnostics) {
            VStack(alignment: .leading, spacing: 14) {
                Text("Diagnostic").font(.title2.bold())
                ScrollView { Text(model.diagnostics).font(.system(.body, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                HStack { Spacer(); Button("Fermer") { model.showDiagnostics = false }.keyboardShortcut(.defaultAction) }
            }.padding(24).frame(minWidth: 680, minHeight: 430)
        }
        .sheet(isPresented: $model.showEnrichment) {
            SetupView(model: model, enrichment: true)
                .frame(minWidth: 780, minHeight: 680)
        }
    }
}

struct StatusCard: View {
    var title: String
    var detail: String
    var icon: String
    var color: Color
    var body: some View {
        HStack(spacing: 13) {
            Image(systemName: icon).font(.title2).foregroundStyle(color)
            VStack(alignment: .leading) {
                Text(title).font(.headline)
                Text(detail).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
        }.padding(16).frame(maxWidth: .infinity).background(.quaternary.opacity(0.5)).clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

struct FailedView: View {
    @ObservedObject var model: CoachAppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            BrandHeader(subtitle: "L’installation a besoin d’aide")
            Label(model.errorMessage, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red)
            ScrollView { Text(model.log).font(.system(.caption, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                .padding(12).background(.quaternary).clipShape(RoundedRectangle(cornerRadius: 10))
            HStack { Button("Réessayer") { model.retryLastOperation() }.buttonStyle(.borderedProminent); Button("Retour") { model.leaveFailure() }; Spacer() }
        }.padding(28)
    }
}

struct RootView: View {
    @ObservedObject var model: CoachAppModel
    var body: some View {
        Group {
            switch model.phase {
            case .welcome: SetupView(model: model)
            case .installing: InstallingView(model: model)
            case .ready: ReadyView(model: model)
            case .failed: FailedView(model: model)
            }
        }
        .frame(minWidth: 780, minHeight: 620)
        .task { model.applyPendingEngineUpdate() }
    }
}

struct UpdateSettingsView: View {
    @ObservedObject var updater: AppUpdater
    var body: some View {
        Form {
            Toggle("Rechercher automatiquement les mises à jour", isOn: Binding(
                get: { updater.automaticallyChecks }, set: { updater.automaticallyChecks = $0 }))
            Toggle("Télécharger et installer automatiquement", isOn: Binding(
                get: { updater.automaticallyDownloads }, set: { updater.automaticallyDownloads = $0 }))
            Text("Les mises à jour suivent les versions publiées. Vos données personnelles sont conservées.")
                .font(.caption).foregroundStyle(.secondary)
            if !updater.isAvailable {
                Text("Les mises à jour ne sont pas configurées pour cette version de développement.")
            }
        }.padding(24).frame(width: 460).disabled(!updater.isAvailable)
    }
}

struct UpdateCommands: Commands {
    @ObservedObject var updater: AppUpdater
    var body: some Commands {
        CommandGroup(after: .appInfo) {
            Button("Rechercher une mise à jour…") { updater.checkForUpdates() }
                .disabled(!updater.canCheckForUpdates)
        }
    }
}

struct AIRunningCoachApp: App {
    @StateObject private var model = CoachAppModel()
    var body: some Scene {
        WindowGroup { RootView(model: model) }
            .windowStyle(.hiddenTitleBar)
            .commands {
                CommandGroup(replacing: .newItem) {}
                UpdateCommands(updater: model.appUpdater)
            }
        Settings { UpdateSettingsView(updater: model.appUpdater) }
    }
}

// Vérifie le chargement réel de toutes les bibliothèques sans initialiser le
// modèle, ouvrir de fenêtre, lire le profil ou déclencher une mise à jour.
@main
enum CoachEntryPoint {
    @MainActor
    static func main() {
        if CommandLine.arguments.contains("--smoke-test") {
            print("AI Running Coach : bibliothèques chargées.")
            return
        }
        AIRunningCoachApp.main()
    }
}
