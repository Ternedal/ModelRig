package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.net.ChatResult

/**
 * #966 (#779 pkt. 8): every Tools reply bubble carries the rig as its source.
 *
 * Tools (`/tools/chat`, approve/deny) are served by the backend/worker only --
 * there is no cloud path for them (ADR: tools run locally regardless of
 * routing). The toolbar already says RIG after a successful Tools turn; the
 * bubble's identity row must say the same, or the operator sees a toolbar
 * truth the message itself does not carry. This is the one place that truth
 * is spelled out, so a future "tools via cloud" has one line to change and one
 * test to fail.
 */
internal fun toolsReplySource(): ChatResult.Source = ChatResult.Source.LOCAL
