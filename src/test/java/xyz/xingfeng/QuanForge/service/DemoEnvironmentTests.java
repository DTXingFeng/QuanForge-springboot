package xyz.xingfeng.QuanForge.service;

import okhttp3.*;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;
import xyz.xingfeng.QuanForge.client.*;

import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Intercept requests inside OkHttp: no socket is opened and all credentials are fictional. */
class DemoEnvironmentTests {
    @Test void defaultClientMustBlockAllAccountWritesBeforeCreatingRequest() {
        AtomicReference<Request> request = new AtomicReference<>();
        BybitPostClient client = new BybitPostClient(mock(ProxyConfigService.class), new BybitModeHolder()) {
            @Override protected OkHttpClient obtainClient() { return capturing(request); }
        };
        assertThatThrownBy(() -> client.postDemo("fake", "fake", "/v5/order/create", "{}"))
                .isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(() -> client.post("fake", "fake", "/v5/order/create", "{}"))
                .isInstanceOf(IllegalStateException.class);
        assertThat(request.get()).isNull();
    }
    OkHttpClient capturing(AtomicReference<Request> captured) {
        return new OkHttpClient.Builder().addInterceptor(chain -> {
            captured.set(chain.request());
            return new Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                    .code(200).message("mock").body(ResponseBody.create("{}", MediaType.get("application/json"))).build();
        }).build();
    }

    @Test void demoPostCannotFollowGlobalRealMode() throws Exception {
        BybitModeHolder mode = new BybitModeHolder(); mode.setMode(BybitMode.REAL);
        AtomicReference<Request> request = new AtomicReference<>();
        BybitPostClient client = new BybitPostClient(mock(ProxyConfigService.class), mode) {
            @Override protected OkHttpClient obtainClient() { return capturing(request); }
        };
        org.springframework.test.util.ReflectionTestUtils.setField(client,"accountWritesEnabled",true);
        client.postDemo("fake-key", "fake-secret", "/v5/order/create", "{}");
        assertThat(request.get().url().host()).isEqualTo("api-demo.bybit.com");
        assertThat(mode.getMode()).isEqualTo(BybitMode.REAL);
    }

    @Test void demoGetCannotReadRealAccountAfterModeSwitch() throws Exception {
        BybitModeHolder mode = new BybitModeHolder(); mode.setMode(BybitMode.REAL);
        AtomicReference<Request> request = new AtomicReference<>();
        BybitGetClient client = new BybitGetClient(mock(ProxyConfigService.class), mode) {
            @Override protected OkHttpClient obtainClient() { return capturing(request); }
        };
        client.getDemo("fake-key", "fake-secret", "/v5/position/list", Map.of("category","linear"));
        assertThat(request.get().url().host()).isEqualTo("api-demo.bybit.com");
    }

    @Test void missingExactDemoCredentialDoesNotFallBackToAnotherAccount() {
        ApiCredentialService credentials = mock(ApiCredentialService.class);
        when(credentials.findByName("bybit")).thenReturn(Optional.empty());
        BybitPostClient posts = mock(BybitPostClient.class);
        BybitService service = new BybitService(mock(BybitGetClient.class), posts, credentials, new ObjectMapper());
        assertThatThrownBy(() -> service.postDemo("bybit","/v5/order/create","{}"))
                .isInstanceOf(xyz.xingfeng.QuanForge.exception.NotFoundException.class);
        verifyNoInteractions(posts);
        verify(credentials, never()).findAll();
    }
}
