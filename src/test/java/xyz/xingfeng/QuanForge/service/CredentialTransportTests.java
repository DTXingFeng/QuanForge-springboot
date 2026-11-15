package xyz.xingfeng.QuanForge.service;

import okhttp3.*;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import xyz.xingfeng.QuanForge.client.*;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class CredentialTransportTests {
    @Test void unsupportedMetadataFallsBackToReadOnlyWithoutClaimingExpiryOrTradingValidity() throws Exception {
        var credentials=mock(ApiCredentialService.class);var client=mock(BybitGetClient.class);
        var credential=new xyz.xingfeng.QuanForge.entity.ApiCredential();credential.setId(3L);
        credential.setApiKey("fake-key");credential.setApiSecret("fake-secret");
        when(credentials.findById(3L)).thenReturn(java.util.Optional.of(credential));
        when(client.probeKeyInformation(BybitMode.DEMO,"fake-key","fake-secret"))
                .thenReturn(new BybitGetClient.SignedResponse(404,"{}"));
        when(client.probeCredentials(BybitMode.DEMO,"fake-key","fake-secret"))
                .thenReturn(new BybitGetClient.SignedResponse(200,"{\"retCode\":0,\"result\":{\"list\":[]}}"));
        var result=new CredentialValidationService(credentials,client,new CredentialHealthRegistry()).validate(3L,BybitMode.DEMO);
        assertThat(result.status()).isEqualTo("READ_ONLY_OK");assertThat(result.level()).isEqualTo("warning");
        assertThat(result.expiresAt()).isNull();assertThat(result.toString()).doesNotContain("fake-key","fake-secret");
    }

    @Test void transportExceptionIsSanitizedAndNeverReportedAsExpired() throws Exception {
        var credentials=mock(ApiCredentialService.class);var client=mock(BybitGetClient.class);
        var credential=new xyz.xingfeng.QuanForge.entity.ApiCredential();credential.setApiKey("fake-key");credential.setApiSecret("fake-secret");
        when(credentials.findById(3L)).thenReturn(java.util.Optional.of(credential));
        when(client.probeKeyInformation(BybitMode.DEMO,"fake-key","fake-secret")).thenThrow(new java.io.IOException("proxy fake-secret"));
        var result=new CredentialValidationService(credentials,client,new CredentialHealthRegistry()).validate(3L,BybitMode.DEMO);
        assertThat(result.status()).isEqualTo("NETWORK_ERROR");
        assertThat(result.toString()).doesNotContain("fake-key","fake-secret");
    }
    @Test void ordinaryDemoRequestsUpdateHealthAndPublicRequestsDoNotValidateCredentials() throws Exception {
        var health=new CredentialHealthRegistry();var holder=new BybitModeHolder();holder.setMode(BybitMode.REAL);
        var request=new AtomicReference<Request>();
        var client=new BybitGetClient(mock(ProxyConfigService.class),holder) {
            protected OkHttpClient obtainClient() {
                return new OkHttpClient.Builder().addInterceptor(chain->{
                    request.set(chain.request());
                    return new Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(200).message("mock")
                            .body(ResponseBody.create("{\"retCode\":33004}",MediaType.get("application/json"))).build();
                }).build();
            }
        };
        ReflectionTestUtils.setField(client,"credentialHealth",health);
        client.getDemo("fake","secret","/v5/account/wallet-balance",Map.of("accountType","UNIFIED"));
        assertThat(request.get().url().host()).isEqualTo("api-demo.bybit.com");
        assertThat(health.current("fake","secret",BybitMode.DEMO).status()).isEqualTo("EXPIRED");
        assertThat(health.current("fake","secret",BybitMode.REAL).status()).isEqualTo("NOT_CHECKED");
        client.getPublic("/v5/market/tickers",Map.of());
        assertThat(request.get().header("X-BAPI-API-KEY")).isNull();
        assertThat(health.current("fake","secret",BybitMode.REAL).status()).isEqualTo("NOT_CHECKED");
    }

    @Test void metadataValidationIsReadOnlyAndPinnedDespiteGlobalMode() throws Exception {
        var holder=new BybitModeHolder();holder.setMode(BybitMode.REAL);var request=new AtomicReference<Request>();
        var client=new BybitGetClient(mock(ProxyConfigService.class),holder) {
            protected OkHttpClient obtainClient() {
                return new OkHttpClient.Builder().addInterceptor(chain->{request.set(chain.request());
                    return new Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(200).message("mock")
                            .body(ResponseBody.create("{\"retCode\":0}",MediaType.get("application/json"))).build();}).build();
            }
        };
        client.probeKeyInformation(BybitMode.DEMO,"fake","secret");
        assertThat(request.get().method()).isEqualTo("GET");
        assertThat(request.get().url().encodedPath()).isEqualTo("/v5/user/query-api");
        assertThat(request.get().url().host()).isEqualTo("api-demo.bybit.com");
        assertThat(holder.getMode()).isEqualTo(BybitMode.REAL);
    }
}
