package xyz.xingfeng.QuanForge.paper;

import org.json.JSONObject;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.UUID;

@Service
public class PaperService {
    private final Path root;
    public PaperService(@Value("${app.paper.root:data/paper-vnext}") String root) { this.root=Path.of(root).toAbsolutePath(); }
    public Path root() { return root; }
    public JSONObject status() throws IOException {
        Path report=root.resolve("report.json");
        if (!Files.isRegularFile(report) || Files.size(report)>2_000_000) throw new IOException("report unavailable");
        JSONObject value=new JSONObject(Files.readString(report));
        value.put("server_now",System.currentTimeMillis());
        value.put("report_age_ms",Math.max(0,System.currentTimeMillis()-value.getLong("heartbeat")));
        Path research=root.resolve("research-summary.json");
        if (Files.isRegularFile(research) && Files.size(research)<2_000_000) value.put("research",new JSONObject(Files.readString(research)));
        Path carry=root.resolve("carry-evidence.json");
        if (Files.isRegularFile(carry) && Files.size(carry)<200_000) value.put("carry_research",new JSONObject(Files.readString(carry)));
        return value;
    }
    public JSONObject control(String action) throws IOException {
        if (!action.equals("PAUSE") && !action.equals("RESUME") && !action.equals("CLOSE")) throw new IllegalArgumentException("unknown action");
        JSONObject command=new JSONObject().put("id",UUID.randomUUID().toString()).put("action",action).put("at",System.currentTimeMillis());
        writeAtomic(root.resolve("control.json"),command.toString());return command;
    }
    public static void writeAtomic(Path path,String value) throws IOException {
        Files.createDirectories(path.toAbsolutePath().getParent());
        Path temp=Files.createTempFile(path.toAbsolutePath().getParent(),"paper-",".tmp");
        try {
            Files.writeString(temp,value,StandardCharsets.UTF_8);
            try { Files.setPosixFilePermissions(temp,java.nio.file.attribute.PosixFilePermissions.fromString("rw-------")); }
            catch (UnsupportedOperationException ignored) { }
            try { Files.move(temp,path,StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE); }
            catch (AtomicMoveNotSupportedException e) { Files.move(temp,path,StandardCopyOption.REPLACE_EXISTING); }
        } finally { Files.deleteIfExists(temp); }
    }
}
