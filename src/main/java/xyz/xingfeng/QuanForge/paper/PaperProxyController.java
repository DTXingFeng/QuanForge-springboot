package xyz.xingfeng.QuanForge.paper;

import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.json.JSONObject;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import xyz.xingfeng.QuanForge.entity.ProxyConfig;
import xyz.xingfeng.QuanForge.entity.ProxyType;
import xyz.xingfeng.QuanForge.service.ProxyConfigService;
import java.io.IOException;

/** Reuses the application's existing proxy singleton, preserving optional auth. */
@RestController
@RequestMapping("/api/paper/proxy")
public class PaperProxyController {
    private final ProxyConfigService service;private final PaperService paper;private final boolean only;
    public PaperProxyController(ProxyConfigService service,PaperService paper,@Value("${app.paper-only:false}") boolean only) {
        this.service=service;this.paper=paper;this.only=only;
    }
    @EventListener(ApplicationReadyEvent.class) public void ready() throws IOException {if (only) publish();}
    private ProxyConfig current() {
        return service.getConfig().orElseGet(()->{
            ProxyConfig p=new ProxyConfig();p.setEnabled(false);p.setType(ProxyType.HTTP);p.setHost("127.0.0.1");p.setPort(7890);return p;
        });
    }
    private void publish() throws IOException {
        ProxyConfig p=current();JSONObject value=new JSONObject().put("enabled",Boolean.TRUE.equals(p.getEnabled()))
            .put("type",p.getType().name()).put("host",p.getHost()).put("port",p.getPort())
            .put("username",p.getUsername()==null?"":p.getUsername()).put("password",p.getPassword()==null?"":p.getPassword());
        PaperService.writeAtomic(paper.root().resolve(".proxy-runtime.json"),value.toString());
    }
    private ResponseEntity<String> safe(ProxyConfig p) {
        JSONObject value=new JSONObject().put("enabled",Boolean.TRUE.equals(p.getEnabled())).put("type",p.getType().name())
            .put("host",p.getHost()).put("port",p.getPort()).put("authConfigured",p.getUsername()!=null&&!p.getUsername().isBlank());
        return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(value.toString());
    }
    @GetMapping public ResponseEntity<String> get() throws IOException {if (only) publish();return safe(current());}
    public record Request(@NotBlank String host,@NotNull @Min(1) @Max(65535) Integer port,@NotNull Boolean enabled) {}
    @PutMapping public ResponseEntity<String> save(@Valid @RequestBody Request request) throws IOException {
        ProxyConfig p=current();p.setHost(request.host().trim());p.setPort(request.port());p.setEnabled(request.enabled());p.setType(ProxyType.HTTP);
        // Existing username/password stay unchanged; never return or log them.
        ProxyConfig saved=service.save(p);publish();return safe(saved);
    }
}
