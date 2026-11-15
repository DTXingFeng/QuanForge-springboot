package xyz.xingfeng.QuanForge.service;

import org.junit.jupiter.api.Test;
import xyz.xingfeng.QuanForge.client.BybitMode;
import java.time.*;
import static org.assertj.core.api.Assertions.*;

class CredentialHealthTests {
    @Test void expiredHttp200IsExplicitAndUpstreamSecretsAreNeverEchoed() {
        var registry=new CredentialHealthRegistry();
        var health=registry.observe("fake-key","fake-secret",BybitMode.DEMO,200,
                "{\"retCode\":33004,\"retMsg\":\"fake-key fake-secret expired\"}");
        assertThat(health.status()).isEqualTo("EXPIRED");
        assertThat(health.message()).contains("过期").doesNotContain("fake-key","fake-secret");
        assertThat(registry.current("fake-key","new-secret",BybitMode.DEMO).status()).isEqualTo("NOT_CHECKED");
        assertThat(registry.current("fake-key","fake-secret",BybitMode.REAL).status()).isEqualTo("NOT_CHECKED");
    }
    @Test void timeoutClockPermissionIpAndRateLimitMustNotBeMislabelledExpired() {
        var registry=new CredentialHealthRegistry();
        int[] codes={10002,10005,10010,10006,10003,10004};
        String[] statuses={"CLOCK_ERROR","PERMISSION_DENIED","IP_RESTRICTED","RATE_LIMITED","INVALID_OR_ENVIRONMENT","SIGNATURE_ERROR"};
        for(int i=0;i<codes.length;i++) assertThat(registry.observe("k","s",BybitMode.DEMO,200,"{\"retCode\":"+codes[i]+"}").status()).isEqualTo(statuses[i]);
        assertThat(registry.networkFailure("k","s",BybitMode.DEMO).status()).isEqualTo("NETWORK_ERROR");
        assertThat(registry.observe("k","s",BybitMode.DEMO,403,"<html>blocked</html>").status()).isEqualTo("FORBIDDEN");
        assertThat(registry.observe("k","s",BybitMode.DEMO,503,"{}").status()).isEqualTo("SERVER_ERROR");
    }
    @Test void freshSuccessRecoversAndOldSuccessBecomesStale() {
        class MutableClock extends Clock {
            long time=1000;
            public ZoneId getZone(){return ZoneOffset.UTC;}
            public Clock withZone(ZoneId zone){return this;}
            public Instant instant(){return Instant.ofEpochMilli(time);}
        }
        var clock=new MutableClock();var registry=new CredentialHealthRegistry(clock);
        registry.observe("k","s",BybitMode.DEMO,200,"{\"retCode\":33004}");
        registry.observe("k","s",BybitMode.DEMO,200,"{\"retCode\":0,\"result\":{\"expiredAt\":\"2030-01-01T00:00:00Z\",\"deadlineDay\":100}}");
        assertThat(registry.current("k","s",BybitMode.DEMO).status()).isEqualTo("VALID");
        clock.time+=300001;
        registry.observe("k","s",BybitMode.DEMO,200,"{\"retCode\":0}");
        // Frequent wallet successes cannot keep old expiry metadata fresh forever.
        assertThat(registry.current("k","s",BybitMode.DEMO).status()).isEqualTo("STALE");
    }

    @Test void zeroDaysWithFutureExpiryMustWarnRatherThanClaimExpired() {
        var registry=new CredentialHealthRegistry(Clock.fixed(Instant.parse("2026-11-14T10:00:00Z"),ZoneOffset.UTC));
        var h=registry.observe("k","s",BybitMode.DEMO,200,"{\"retCode\":0,\"result\":{\"deadlineDay\":0,\"expiredAt\":\"2026-11-15T06:01:20Z\",\"readOnly\":0,\"permissions\":{\"ContractTrade\":[\"Order\",\"Position\"]}}}");
        assertThat(h.status()).isEqualTo("EXPIRING");
        assertThat(h.expiresAt()).isEqualTo("2026-11-15T06:01:20Z");
        assertThat(h.tradePermissionConfigured()).isTrue();
        assertThat(registry.observe("k","s",BybitMode.DEMO,200,"{\"retCode\":0}").status()).isEqualTo("EXPIRING");
    }

    @Test void expiredMetadataOverridesSuccessfulWalletAndUnknownMetadataNeverTurnsGreen() {
        var registry=new CredentialHealthRegistry(Clock.fixed(Instant.parse("2026-11-14T10:00:00Z"),ZoneOffset.UTC));
        assertThat(registry.observe("k","s",BybitMode.DEMO,200,"{\"retCode\":0}").status()).isEqualTo("READ_ONLY_OK");
        var h=registry.observe("k","s",BybitMode.DEMO,200,"{\"retCode\":0,\"result\":{\"deadlineDay\":0,\"expiredAt\":\"2026-11-13T06:01:20Z\"}}");
        assertThat(h.status()).isEqualTo("EXPIRED");
        assertThat(registry.observe("k","s",BybitMode.DEMO,200,"{\"retCode\":0}").status()).isEqualTo("EXPIRED");
    }
}
