package xyz.xingfeng.QuanForge.paper;

import org.json.JSONObject;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import xyz.xingfeng.QuanForge.SystemVersion;
import java.io.IOException;
import java.util.Map;

@RestController
public class PaperController {
    private final PaperService service;private final boolean only;
    public PaperController(PaperService service,@Value("${app.paper-only:false}") boolean only) {this.service=service;this.only=only;}
    @GetMapping("/api/runtime") public Map<String,Object> runtime() {
        return Map.of("paperOnly",only,"version",SystemVersion.CURRENT,"realOrderCapability",!only);
    }
    @GetMapping("/api/paper/status") public ResponseEntity<String> status() {
        try {return json(200,service.status());}
        catch (IOException|RuntimeException e) {return json(503,new JSONObject().put("code","PAPER_REPORT_UNAVAILABLE").put("message","纸面引擎正在启动或暂不可用"));}
    }
    public record Control(String action) {}
    @PostMapping("/api/paper/control") public ResponseEntity<String> control(@RequestBody Control request) {
        try {return json(202,service.control(request.action()==null?"":request.action()));}
        catch (IllegalArgumentException e) {return json(400,new JSONObject().put("code","INVALID_CONTROL").put("message","操作只支持暂停、恢复或结束纸面持仓"));}
        catch (IOException e) {return json(503,new JSONObject().put("code","CONTROL_UNAVAILABLE").put("message","暂时无法提交操作"));}
    }
    private ResponseEntity<String> json(int code,JSONObject body) {return ResponseEntity.status(code).contentType(MediaType.APPLICATION_JSON).body(body.toString());}
}
