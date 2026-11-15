package xyz.xingfeng.QuanForge.service;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.util.ReflectionTestUtils;
import xyz.xingfeng.QuanForge.entity.AiAdviceTrack;
import java.nio.file.Path;
import static org.assertj.core.api.Assertions.*;

class ExecutionJournalTests {
    @TempDir Path folder;
    @Test void observationsPersistAcrossRestartAndDuplicatesDoNotOverwritePriorStop() {
        var jdbc=new JdbcTemplate(new DriverManagerDataSource("jdbc:sqlite:"+folder.resolve("journal.db")));
        var journal=new ExecutionJournal(jdbc);
        var t=new AiAdviceTrack(); ReflectionTestUtils.setField(t,"id",7L);
        t.setSymbol("BTCUSDT");t.setAction("BUY");t.setStatus("TRACKING");
        t.setEntry(100.0);t.setStopLoss(95.0);t.setTakeProfit(110.0);
        journal.record(t,"PROTECTION_CHANGE_ACK","response, not fill");
        journal.record(t,"PROTECTION_CHANGE_ACK","response, not fill");
        t.setStopLoss(98.0);journal.record(t,"PROTECTION_CHANGE_ACK","response, not fill");
        var recovered=new ExecutionJournal(jdbc).events(7);
        assertThat(recovered).hasSize(2);
        assertThat(recovered.toString()).contains("95", "98");
    }
}
