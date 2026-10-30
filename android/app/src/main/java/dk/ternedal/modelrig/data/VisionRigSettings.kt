package dk.ternedal.modelrig.data

import dk.ternedal.modelrig.logic.StoredCredentialRead
import dk.ternedal.modelrig.net.VisionRigConnection

/** What the VisionRig camera screen reads and writes. Production: [TokenStore]. */
interface VisionRigSettings {
    /** The paired gateway, or null when not paired or the stored token is unreadable. */
    fun connection(): VisionRigConnection?

    /** A token is stored but cannot be decrypted (e.g. new Keystore): fail closed, ask to re-pair. */
    fun credentialUnreadable(): Boolean

    fun cameraOptIn(): Boolean

    /** True only after a confirmed synchronous commit. */
    fun save(connection: VisionRigConnection): Boolean
    fun setCameraOptIn(on: Boolean): Boolean
    fun clear(): Boolean
}

class TokenStoreVisionRigSettings(private val store: TokenStore) : VisionRigSettings {
    override fun connection(): VisionRigConnection? {
        val token = (store.visionRigCredentialStatus as? StoredCredentialRead.Ready)?.value ?: return null
        // A stored value that no longer passes today's policy is not used.
        return VisionRigConnection.create(store.visionRigGatewayUrl, token).getOrNull()
    }

    override fun credentialUnreadable(): Boolean = store.visionRigCredentialStatus is StoredCredentialRead.Invalid

    override fun cameraOptIn(): Boolean = store.visionRigCameraOptIn

    override fun save(connection: VisionRigConnection): Boolean =
        store.saveVisionRigConnection(connection.gatewayUrl, connection.token)

    override fun setCameraOptIn(on: Boolean): Boolean = store.setVisionRigCameraOptIn(on)

    override fun clear(): Boolean = store.clearVisionRig()
}
