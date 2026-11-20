package com.junze.futureme.ui.nav

/** Bottom-nav tabs. */
object Routes {
    const val HOME = "home"
    const val LETTERS = "letters"
    const val DAILY = "daily"
    const val ME = "me"

    /** Account (email registration / login) and privacy policy. */
    const val ACCOUNT = "account"
    const val PRIVACY = "privacy"

    /** Wish detail: wish info + its letters + generate button. */
    const val WISH_DETAIL = "wish/{wishId}"
    fun wishDetail(wishId: String) = "wish/$wishId"

    /** Letter detail: full text + audio player. */
    const val LETTER_DETAIL = "letter/{letterId}"
    fun letterDetail(letterId: String) = "letter/$letterId"
}
