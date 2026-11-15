package xyz.xingfeng.QuanForge.service;

import org.json.JSONObject;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import xyz.xingfeng.QuanForge.entity.AiAdviceTrack;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;

/** Append-only observations, not proof of a fill or a substitute for execution/cashflow reconciliation. */
@Service
public class ExecutionJournal {
    private final JdbcTemplate jdbc;
    public ExecutionJournal(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
        jdbc.execute("create table if not exists execution_event (event_id varchar(64) primary key, "
                + "track_id bigint not null, kind varchar(32) not null, observed_at bigint not null, payload text not null)");
    }

    public void record(AiAdviceTrack track, String kind, String evidence) {
        if (track.getId() == null) throw new IllegalStateException("journal requires committed track identity");
        JSONObject data = new JSONObject().put("symbol",track.getSymbol()).put("action",track.getAction())
                .put("status",track.getStatus()).put("orderLinkId",track.getOrderLinkId())
                .put("orderId",track.getOrderId()).put("entry",track.getEntry()).put("stopLoss",track.getStopLoss())
                .put("takeProfit",track.getTakeProfit()).put("qty",track.getQty()).put("evidence",evidence);
        String payload=data.toString();
        try {
            String identity=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(
                    (track.getId()+"|"+kind+"|"+payload).getBytes(StandardCharsets.UTF_8)));
            jdbc.update("insert into execution_event values(?,?,?,?,?) on conflict(event_id) do nothing",
                    identity, track.getId(),kind,System.currentTimeMillis(),payload);
        } catch (java.security.NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    public List<Map<String,Object>> events(long trackId) {
        return jdbc.queryForList("select kind,observed_at,payload from execution_event where track_id=? order by observed_at,event_id", trackId);
    }
}
