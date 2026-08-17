package com.boellund.wagvid.capture.network

import org.junit.Assert.assertNotNull
import org.junit.Test

class TlsPinTest {
    private val validPin = "sha256/${"A".repeat(43)}="

    @Test
    fun validSpkiPinCanBuildPinnedHttpsClientWithoutNetworkIo() {
        assertNotNull(ApiFactory.client("https://example.com/", validPin))
    }

    @Test(expected = IllegalArgumentException::class)
    fun malformedPinIsRejected() {
        TlsPin.requireValid("sha256/not-a-real-pin")
    }

    @Test(expected = IllegalArgumentException::class)
    fun pinningCannotBeEnabledForPlainHttp() {
        ApiFactory.client("http://127.0.0.1:8000/", validPin)
    }

    @Test
    fun debugHttpCanStillBuildClientWhenNoPinIsRequested() {
        assertNotNull(ApiFactory.client("http://127.0.0.1:8000/", null))
    }
}
