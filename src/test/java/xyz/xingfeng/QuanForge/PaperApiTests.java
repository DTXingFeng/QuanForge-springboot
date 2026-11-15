package xyz.xingfeng.QuanForge;

import org.json.JSONObject;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import xyz.xingfeng.QuanForge.entity.ProxyConfig;
import xyz.xingfeng.QuanForge.entity.ProxyType;
import xyz.xingfeng.QuanForge.service.BybitService;
import xyz.xingfeng.QuanForge.service.ProxyConfigService;

import java.net.URI;
import java.net.http.*;
import java.nio.file.*;
import java.util.Optional;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties={
    "app.paper-only=true","app.scheduling.enabled=false","app.execution.account-writes-enabled=false"})
class PaperApiTests {
    static final Path ROOT=Path.of("target","paper-api-"+System.nanoTime()).toAbsolutePath();
    @DynamicPropertySource static void root(DynamicPropertyRegistry r){r.add("app.paper.root",()->ROOT.toString());}
    @LocalServerPort int port;
    @MockitoBean BybitService bybit;
    @MockitoBean ProxyConfigService proxies;
    final HttpClient http=HttpClient.newHttpClient();
    HttpResponse<String> call(String method,String path,String body,String origin)throws Exception{
        var b=HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+path));
        if(origin!=null)b.header("Origin",origin);
        if(body!=null)b.header("Content-Type","application/json");
        b.method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(body));
        return http.send(b.build(),HttpResponse.BodyHandlers.ofString());
    }
    @Test void paperReleaseBlocksAllLegacyAccountPathsBeforeAnyServiceCall()throws Exception{
        assertThat(new JSONObject(call("GET","/api/runtime",null,null).body()).getBoolean("paperOnly")).isTrue();
        assertThat(call("GET","/api/credentials",null,null).statusCode()).isEqualTo(403);
        assertThat(call("POST","/api/bybit/create-order","{}",null).statusCode()).isEqualTo(403);
        verifyNoInteractions(bybit);
    }
    @Test void unavailableStatusAndCrossOriginControlsFailVisibly()throws Exception{
        assertThat(call("GET","/api/paper/status",null,null).statusCode()).isEqualTo(503);
        assertThat(call("POST","/api/paper/control","{\"action\":\"PAUSE\"}","https://example.invalid").statusCode()).isEqualTo(403);
        assertThat(call("POST","/api/paper/control","{\"action\":\"RESET\"}",null).statusCode()).isEqualTo(400);
        assertThat(call("POST","/api/paper/control","{\"action\":\"PAUSE\"}",null).statusCode()).isEqualTo(202);
        assertThat(new JSONObject(Files.readString(ROOT.resolve("control.json"))).getString("action")).isEqualTo("PAUSE");
    }
    @Test void appProxyRemainsSingleSourceAndNeverReturnsAuthSecrets()throws Exception{
        ProxyConfig p=new ProxyConfig();p.setType(ProxyType.HTTP);p.setHost("127.0.0.1");p.setPort(7890);p.setEnabled(true);
        p.setUsername("fake-proxy-user");p.setPassword("fake-proxy-password");
        when(proxies.getConfig()).thenReturn(Optional.of(p));when(proxies.save(any())).thenAnswer(i->i.getArgument(0));
        String body=call("GET","/api/paper/proxy",null,null).body();
        assertThat(body).doesNotContain("fake-proxy-user","fake-proxy-password");
        assertThat(new JSONObject(body).getInt("port")).isEqualTo(7890);
        var saved=call("PUT","/api/paper/proxy","{\"host\":\"127.0.0.1\",\"port\":7891,\"enabled\":true}",null);
        assertThat(saved.statusCode()).isEqualTo(200);assertThat(saved.body()).doesNotContain("fake-proxy-password");
        var runtime=new JSONObject(Files.readString(ROOT.resolve(".proxy-runtime.json")));
        assertThat(runtime.getInt("port")).isEqualTo(7891);assertThat(runtime.getString("password")).isEqualTo("fake-proxy-password");
    }
}
