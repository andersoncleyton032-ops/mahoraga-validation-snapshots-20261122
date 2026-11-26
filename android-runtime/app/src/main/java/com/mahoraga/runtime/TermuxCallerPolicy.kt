package com.mahoraga.runtime

internal object TermuxCallerPolicy {
    const val TERMUX_PACKAGE = "com.termux"

    fun isTrusted(
        callingUid: Int,
        packagesForUid: Array<String>?,
        installedTermuxUid: Int,
        signerTrusted: Boolean
    ): Boolean {
        return callingUid >= 0
            && installedTermuxUid >= 0
            && callingUid == installedTermuxUid
            && packagesForUid?.contains(TERMUX_PACKAGE) == true
            && signerTrusted
    }
}
