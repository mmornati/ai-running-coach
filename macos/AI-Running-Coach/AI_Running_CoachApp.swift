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
        case .gemini: return "Gemini CLI"
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
    var openRouterAPIKey = ""
    var chatBudget = "1.00"
    var source: DataSource = .garmin
    var ide: IDEChoice = .claude
    var coachingStyle: CoachingStyle = .bienveillant
    var sport: SportChoice = .trail
    var morningCheck: MorningCheck = .full
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
        let key = openRouterAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty, !key.contains("\n"), !key.contains("\r") else { return false }
        guard let budget = Double(chatBudget.replacingOccurrences(of: ",", with: ".")) else { return false }
        return budget > 0
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
    @Published var updateAvailable = false
    @Published private(set) var wasUpdating = false
    @Published var showOptionalProfile = false
    @Published var showEnrichment = false
    @Published var enrichmentSaving = false
    @Published var enrichmentError = ""

    private var dashboardProcess: Process?
    private let fm = FileManager.default
    private let defaults = UserDefaults.standard

    var appSupport: URL {
        fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("AI Running Coach", isDirectory: true)
    }

    var engineURL: URL { appSupport.appendingPathComponent("engine", isDirectory: true) }
    var workspaceURL: URL { URL(fileURLWithPath: choices.workspace).standardizedFileURL }
    var bundleVersion: String { Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "development" }

    var isInstalled: Bool {
        fm.isExecutableFile(atPath: engineURL.appendingPathComponent("install.sh").path)
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
    var externalAssistantTitle: String { choices.ide.title }

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
        if defaults.bool(forKey: "integratedChatEnabled") {
            choices.chatChoice = .integrated
        }
        phase = isInstalled ? .ready : .welcome
        updateAvailable = isInstalled && defaults.string(forKey: "engineVersion") != bundleVersion
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

        Task {
            do {
                try await ensureDeveloperTools()
                try await installEngine()
                if selected.chatChoice == .integrated {
                    progress = 0.16
                    progressTitle = "Préparation du chat avec le coach"
                    try saveOpenRouterKey(selected.openRouterAPIKey)
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
                    "--ide", selected.ide.rawValue,
                    "--agents", selected.agents.joined(separator: ","),
                    "--no-auth"
                ]
                if selected.chatChoice == .integrated {
                    args += [
                        "--llm", "openrouter",
                        "--chat",
                        "--chat-budget", selected.chatBudget.replacingOccurrences(of: ",", with: ".")
                    ]
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
                defaults.set(selected.chatChoice == .integrated, forKey: "integratedChatEnabled")
                defaults.set(selected.ide.rawValue, forKey: "assistant")
                defaults.set(bundleVersion, forKey: "engineVersion")
                choices.openRouterAPIKey = ""
                updateAvailable = false
                progress = 1
                progressTitle = "Installation terminée"
                phase = .ready
            } catch {
                errorMessage = error.localizedDescription
                appendLog("\nErreur : \(error.localizedDescription)\n")
                phase = .failed
            }
        }
    }

    func updateEngine() {
        wasUpdating = true
        phase = .installing
        progress = 0.05
        progressTitle = "Mise à jour du moteur"
        log = ""
        errorMessage = ""
        Task {
            do {
                try await ensureDeveloperTools()
                try await installEngine()
                progress = 0.35
                progressTitle = "Vérification des composants"
                let result = try await runProcess(
                    executable: "/bin/bash",
                    arguments: [
                        engineURL.appendingPathComponent("install.sh").path,
                        "--workspace", workspaceURL.path,
                        "--source", choices.source.rawValue,
                        "--ide", choices.ide.rawValue,
                        "--no-auth"
                    ],
                    directory: engineURL,
                    streamOutput: true
                )
                guard result.code == 0 else { throw AppFailure("La mise à jour s’est arrêtée (code \(result.code)).") }
                defaults.set(bundleVersion, forKey: "engineVersion")
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

    private func saveOpenRouterKey(_ rawKey: String) throws {
        let key = rawKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty, !key.contains("\n"), !key.contains("\r") else {
            throw AppFailure("La clé OpenRouter est vide ou invalide.")
        }
        let directory = fm.homeDirectoryForCurrentUser.appendingPathComponent(".config/ai-running-coach", isDirectory: true)
        let file = directory.appendingPathComponent("llm.env")
        try fm.createDirectory(at: directory, withIntermediateDirectories: true)
        let previous = (try? String(contentsOf: file, encoding: .utf8)) ?? ""
        let kept = previous.split(separator: "\n", omittingEmptySubsequences: false).filter { line in
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            return !trimmed.hasPrefix("OPENROUTER_API_KEY=") && !trimmed.hasPrefix("export OPENROUTER_API_KEY=")
        }
        let contents = kept.joined(separator: "\n").trimmingCharacters(in: .newlines)
            + (kept.isEmpty ? "" : "\n") + "OPENROUTER_API_KEY=\(key)\n"
        try contents.write(to: file, atomically: true, encoding: .utf8)
        try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
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
            arguments: ["install", "--prefix", destination.path, "@google/gemini-cli"],
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
            "coaching.intensity": "balanced",
            "coaching.verbosity": "standard",
            "sport.primary": selected.sport.rawValue,
            "sport.disciplines": [],
            "agents.enabled": selected.agents,
            "health.morning_check": selected.morningCheck.rawValue,
            "language.documents": "fr",
            "language.responses": "auto",
            "athlete.units": "metric"
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
        let destination = openChat ? "http://127.0.0.1:8765/chat.html" : "http://127.0.0.1:8765/"
        if dashboardProcess?.isRunning == true {
            NSWorkspace.shared.open(URL(string: destination)!)
            return
        }
        log = ""
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
                        NSWorkspace.shared.open(openChat ? url.appendingPathComponent("chat.html") : url)
                    }
                }
            }
        }
        process.terminationHandler = { [weak self] _ in
            Task { @MainActor in self?.dashboardRunning = false }
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
            ZStack {
                RoundedRectangle(cornerRadius: 18).fill(Color(red: 0.08, green: 0.25, blue: 0.18))
                Image(systemName: "figure.trail.running").font(.system(size: 35, weight: .semibold)).foregroundStyle(Color(red: 0.64, green: 0.89, blue: 0.20))
            }.frame(width: 72, height: 72)
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
                                Divider()
                                Text("Physiologie — laissez vide ce que vous ne connaissez pas").font(.headline)
                                ProfileField(label: "FC max", placeholder: "182 bpm", text: $model.choices.maxHeartRate)
                                ProfileField(label: "FC de repos", placeholder: "47 bpm, valeur habituelle", text: $model.choices.restingHeartRate)
                                ProfileField(label: "FC au seuil", placeholder: "170 bpm", text: $model.choices.thresholdHeartRate)
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
                    Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 12) {
                        GridRow { Text("Discipline"); Picker("", selection: $model.choices.sport) { ForEach(SportChoice.allCases) { Text($0.title).tag($0) } }.labelsHidden() }
                        GridRow { Text("Style du coach"); Picker("", selection: $model.choices.coachingStyle) { ForEach(CoachingStyle.allCases) { Text($0.title).tag($0) } }.labelsHidden() }
                        GridRow { Text("Bilan du matin"); Picker("", selection: $model.choices.morningCheck) { ForEach(MorningCheck.allCases) { Text($0.title).tag($0) } }.labelsHidden() }
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
                            Text("Vous retrouverez un bouton « Parler au coach » dans l’application. Ce chat utilise OpenRouter et nécessite une clé API facturée à l’usage ; votre plafond quotidien évite les surprises.")
                                .font(.callout).foregroundStyle(.secondary)
                            HStack {
                                Text("Clé OpenRouter").frame(width: 170, alignment: .leading)
                                SecureField("sk-or-v1-…", text: $model.choices.openRouterAPIKey)
                                Link("Créer une clé", destination: URL(string: "https://openrouter.ai/settings/keys")!)
                            }
                            ProfileField(label: "Plafond par jour", placeholder: "1.00", text: $model.choices.chatBudget)
                            Text("La clé est enregistrée uniquement sur ce Mac dans un fichier privé. Les données de la conversation sont envoyées au fournisseur du modèle choisi.")
                                .font(.caption).foregroundStyle(.secondary)
                        } else {
                            Picker("Assistant IA", selection: $model.choices.ide) {
                                ForEach(IDEChoice.guidedCases) { Text($0.title).tag($0) }
                            }
                            Text("L’application installe automatiquement l’assistant choisi. Ensuite, le bouton « Parler au coach » ouvre le bon dossier et lance l’assistant ; sa connexion s’affiche simplement au premier lancement.")
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

            if model.updateAvailable {
                GroupBox {
                    HStack {
                        Label("Une nouvelle version du moteur est incluse dans l’application.", systemImage: "arrow.down.circle.fill")
                        Spacer()
                        Button("Mettre à jour") { model.updateEngine() }.buttonStyle(.borderedProminent)
                    }.padding(8)
                }
            }

            HStack(spacing: 12) {
                if model.integratedChatEnabled {
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

            Divider()
            HStack {
                Button("Vérifier l’installation") { model.runDiagnostics() }
                Button("Compléter mon profil et mon objectif") { model.showEnrichment = true }
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
    @StateObject private var model = CoachAppModel()
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
    }
}

@main
struct AIRunningCoachApp: App {
    var body: some Scene {
        WindowGroup { RootView() }
            .windowStyle(.hiddenTitleBar)
            .commands { CommandGroup(replacing: .newItem) {} }
    }
}
