// Sonde réelle Sparkle : lit un flux local et exige la découverte de la version attendue.
import AppKit
import Sparkle

final class Probe: NSObject, SPUUpdaterDelegate {
    let url = CommandLine.arguments[2]
    let expected = CommandLine.arguments[3]
    func feedURLString(for updater: SPUUpdater) -> String? { url }
    func updater(_ updater: SPUUpdater, didFindValidUpdate item: SUAppcastItem) {
        guard item.displayVersionString == expected else {
            fputs("Version inattendue : \(item.displayVersionString)\n", stderr)
            exit(2)
        }
        print("Sparkle détecte la nouvelle version : \(item.displayVersionString)")
        exit(0)
    }
    func updaterDidNotFindUpdate(_ updater: SPUUpdater, error: Error) {
        if expected == "none" { print("Sparkle confirme : aucune mise à jour disponible."); exit(0) }
        fputs("Aucune mise à jour : \(error)\n", stderr)
        exit(3)
    }
    func updater(_ updater: SPUUpdater, didAbortWithError error: Error) {
        fputs("Vérification interrompue : \(error)\n", stderr)
        exit(4)
    }
}
let probe = Probe()
let bundle = Bundle(path: CommandLine.arguments[1])!
let driver = SPUStandardUserDriver(hostBundle: bundle, delegate: nil)
let updater = SPUUpdater(hostBundle: bundle, applicationBundle: bundle, userDriver: driver, delegate: probe)
try updater.start()
updater.checkForUpdateInformation()
DispatchQueue.main.asyncAfter(deadline: .now() + 30) { fputs("Délai de vérification dépassé\n", stderr); exit(5) }
RunLoop.main.run()
