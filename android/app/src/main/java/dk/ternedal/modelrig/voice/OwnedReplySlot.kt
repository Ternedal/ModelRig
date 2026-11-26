package dk.ternedal.modelrig.voice

/**
 * One write to the list slot a voice turn owns, tracked by identity.
 *
 * The turn owns exactly the bubble instance it stored. A list that was cleared and refilled
 * meanwhile (another conversation) holds other instances, so it is never touched.
 *
 * Returns the instance the turn owns after the write: null once the bubble is removed.
 *
 * Codex #2360 4507627138: a Compose `SnapshotStateList` does not store a replacement that is
 * equal to the current element. It keeps the old instance. Taking ownership of the new,
 * equal-but-distinct instance then failed every later identity check, so later text, the final
 * reply and the cleanup of `streaming` were all dropped. An equal update therefore keeps the
 * current instance, and any other write reads back what the list actually stored.
 */
internal fun <T : Any> updateOwnedSlot(
    list: MutableList<T>,
    index: Int,
    owned: T?,
    update: (T) -> T?,
): T? {
    val mine = owned ?: return null
    if (list.getOrNull(index) !== mine) return mine
    val next = update(mine)
    if (next == null) {
        list.removeAt(index)
        return null
    }
    if (next == mine) return mine
    list[index] = next
    return list[index]
}
