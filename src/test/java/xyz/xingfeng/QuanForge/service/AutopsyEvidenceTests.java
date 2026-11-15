package xyz.xingfeng.QuanForge.service;

import org.junit.jupiter.api.Test;
import xyz.xingfeng.QuanForge.entity.AiAdviceTrack;
import xyz.xingfeng.QuanForge.repository.AiAdviceTrackRepository;
import java.time.LocalDateTime;
import java.util.List;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class AutopsyEvidenceTests {
    @Test void unavailablePriceEvidenceMustNotBeCountedAsALoss() {
        AiAdviceTrack t = new AiAdviceTrack();
        t.setStatus("WIN"); t.setSymbol("TESTUSDT"); t.setAction("BUY");
        t.setEntry(100.); t.setStopLoss(99.); t.setTakeProfit(102.);
        t.setEnteredAt(LocalDateTime.now().minusHours(1)); t.setSettledAt(LocalDateTime.now());
        AiAdviceTrackRepository repository = mock(AiAdviceTrackRepository.class);
        when(repository.findAll()).thenReturn(List.of(t));
        BybitService bybit = mock(BybitService.class);
        when(bybit.getPublicRaw(anyString(), anyMap())).thenThrow(new IllegalStateException("offline"));
        var result = new TradeAutopsyService(repository, bybit, mock(AiConfigService.class),
                mock(xyz.xingfeng.QuanForge.client.ProxiedHttpClients.class)).autopsyRecent(10);
        assertThat(result.taxonomy()).containsEntry("UNKNOWN", 1);
        assertThat(result.losses()).isZero();
        assertThat(result.wins()).isZero();
    }
}
