# shellcheck shell=bash
# Commun à tous les stubs de test. Sourcé, jamais exécuté directement.
#
# Chaque stub journalise son nom et ses arguments dans $ARC_STUB_LOG (une ligne
# par appel, « nom<TAB>args »), ce qui permet aux tests d'affirmer COMMENT un
# outil a été appelé — c'est le seul moyen de tester les chemins crontab et
# launchctl sans toucher à la vraie machine.
#
# $ARC_STUB_FAIL : liste de noms séparés par des virgules qui doivent échouer.

stub_name() { basename "$0"; }

stub_log() {
    [ -n "${ARC_STUB_LOG:-}" ] || return 0
    printf '%s\t%s\n' "$(stub_name)" "$*" >> "$ARC_STUB_LOG"
}

# Renvoie 0 si ce stub doit échouer (déclaré dans $ARC_STUB_FAIL).
stub_should_fail() {
    case ",${ARC_STUB_FAIL:-}," in
        *",$(stub_name),"*) return 0 ;;
        *) return 1 ;;
    esac
}

stub_init() {
    stub_log "$@"
    if stub_should_fail; then
        echo "$(stub_name): échec simulé (ARC_STUB_FAIL)" >&2
        exit 1
    fi
}
