package xyz.xingfeng.QuanForge.service;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import xyz.xingfeng.QuanForge.entity.AiAdviceTrack;
import xyz.xingfeng.QuanForge.repository.AiAdviceTrackRepository;

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** Closed-bar, deterministic OHLC fixtures only. No external requests or Spring startup. */
class PaperSettlementAuditTests {
    BybitService bybit;
    AiAdviceTrackRepository repository;
    AiAdviceTracker tracker;
    long minute;
    int pageCap;

    @BeforeEach void setup() {
        bybit=mock(BybitService.class);
        repository=mock(AiAdviceTrackRepository.class);
        tracker=new AiAdviceTracker(repository,bybit,mock(TelegramBotService.class),mock(DemoOrderExecutor.class),mock(AiConfigService.class));
        minute=System.currentTimeMillis()/60_000*60_000;
        ReflectionTestUtils.setField(tracker,"paperClock",java.time.Clock.fixed(
                java.time.Instant.ofEpochMilli(minute+30_000),java.time.ZoneOffset.UTC));
        pageCap=1000;
    }

    LocalDateTime time(long ms) {
        return LocalDateTime.ofInstant(java.time.Instant.ofEpochMilli(ms),ZoneId.systemDefault());
    }

    AiAdviceTrack paper(String status,long created,long entered) {
        AiAdviceTrack t=new AiAdviceTrack(); t.setSymbol("BTCUSDT"); t.setAction("BUY"); t.setExecMode("PAPER");
        t.setEntry(100.0); t.setStopLoss(95.0); t.setTakeProfit(110.0); t.setStatus(status);
        ReflectionTestUtils.setField(t,"createdAt",time(created));
        if(entered>0)t.setEnteredAt(time(entered));
        when(repository.findByStatusIn(anyList())).thenReturn(List.of(t));
        return t;
    }

    void serve(List<double[]> rows) {
        when(bybit.getPublicRaw(eq("/v5/market/kline"),anyMap())).thenAnswer(inv -> {
            Map<String,String> p=inv.getArgument(1);
            long start=Long.parseLong(p.getOrDefault("start","0"));
            long end=Long.parseLong(p.getOrDefault("end",Long.toString(Long.MAX_VALUE)));
            int limit=Math.min(pageCap,Integer.parseInt(p.getOrDefault("limit","200")));
            JSONArray list=new JSONArray();
            rows.stream().filter(r->r[0]>=start && r[0]<=end).sorted((a,b)->Double.compare(b[0],a[0])).limit(limit)
                    .forEach(r->list.put(new JSONArray().put(Long.toString((long)r[0])).put("100")
                            .put(Double.toString(r[1])).put(Double.toString(r[2])).put(Double.toString(r[3])).put("1")));
            return new JSONObject().put("retCode",0).put("result",new JSONObject().put("list",list)).toString();
        });
    }

    @Test void entryBarStopMustNotDisappearWhenNextBarRebounds() {
        AiAdviceTrack t=paper("PENDING",minute-5*60_000,0);
        ReflectionTestUtils.invokeMethod(tracker,"settleOne",t,List.of(
                new double[]{minute-4*60_000,101,94,99},new double[]{minute-3*60_000,111,99,110}));
        assertThat(t.getStatus()).isEqualTo("LOSS");
        assertThat(t.getResultPct()).isEqualTo(-5);
    }

    @Test void unfinishedCurrentBarMustNotSettlePosition() {
        AiAdviceTrack t=paper("TRACKING",minute-6*60_000,minute-5*60_000);
        List<double[]> rows=new ArrayList<>();
        for(long ms=minute-6*60_000;ms<minute;ms+=60_000)rows.add(new double[]{ms,102,98,100});
        rows.add(new double[]{minute,102,94,96});
        serve(rows);
        tracker.settle();
        assertThat(t.getStatus()).isEqualTo("TRACKING");
    }

    @Test void outageMustReplayOldStopBeyondLatestTwoHundredBars() {
        AiAdviceTrack t=paper("TRACKING",minute-360*60_000,minute-359*60_000);
        List<double[]> rows=new ArrayList<>();
        for(long ms=minute-360*60_000;ms<minute;ms+=60_000)rows.add(new double[]{ms,102,98,100});
        rows.set(2,new double[]{minute-358*60_000,102,94,99});
        serve(rows);
        tracker.settle();
        assertThat(t.getStatus()).isEqualTo("LOSS");
        assertThat(t.getResultPct()).isEqualTo(-5);
    }

    @Test void entryBarTakeProfitMayHavePrecededFillAndMustNotBeAwarded() {
        AiAdviceTrack t=paper("PENDING",minute-5*60_000,0);
        ReflectionTestUtils.invokeMethod(tracker,"settleOne",t,List.of(new double[]{minute-4*60_000,111,99,100}));
        assertThat(t.getStatus()).isEqualTo("TRACKING");
        assertThat(t.getResultPct()).isNull();
    }

    @Test void signalCreationMustNotLookBackIntoEarlierCandle() {
        AiAdviceTrack t=paper("PENDING",minute-5*60_000,0);
        ReflectionTestUtils.invokeMethod(tracker,"settleOne",t,List.of(
                new double[]{minute-6*60_000,112,90,100}, new double[]{minute-4*60_000,105,101,104}));
        assertThat(t.getStatus()).isEqualTo("PENDING");
    }

    @Test void missingMinuteMustKeepUnsettledStateWithoutInventingExit() {
        AiAdviceTrack t=paper("TRACKING",minute-6*60_000,minute-5*60_000);
        List<double[]> rows=new ArrayList<>();
        for(long ms=minute-6*60_000;ms<minute;ms+=60_000)
            if(ms!=minute-3*60_000)rows.add(new double[]{ms,102,98,100});
        serve(rows); tracker.settle();
        assertThat(t.getStatus()).isEqualTo("TRACKING");
        assertThat(t.getResultPct()).isNull();
        verify(repository,never()).save(any());
    }

    @Test void boundedPaginationMustRecoverOlderRequiredBars() {
        AiAdviceTrack t=paper("TRACKING",minute-300*60_000,minute-299*60_000);
        List<double[]> rows=new ArrayList<>();
        for(long ms=minute-300*60_000;ms<minute;ms+=60_000)rows.add(new double[]{ms,102,98,100});
        rows.set(3,new double[]{minute-297*60_000,102,94,99});
        pageCap=100; serve(rows); tracker.settle();
        assertThat(t.getStatus()).isEqualTo("LOSS");
        verify(bybit,times(3)).getPublicRaw(eq("/v5/market/kline"),anyMap());
    }

    @Test void paginationBudgetExhaustionMustNotMutateTracking() {
        AiAdviceTrack t=paper("TRACKING",minute-300*60_000,minute-299*60_000);
        List<double[]> rows=new ArrayList<>();
        for(long ms=minute-300*60_000;ms<minute;ms+=60_000)rows.add(new double[]{ms,102,98,100});
        pageCap=10; serve(rows); tracker.settle();
        assertThat(t.getStatus()).isEqualTo("TRACKING");
        assertThat(t.getResultPct()).isNull();
        verify(bybit,times(4)).getPublicRaw(eq("/v5/market/kline"),anyMap());
        verify(repository,never()).save(any());
    }

    @Test void ttlSettlementMustIgnoreLaterLossAndUseCloseAvailableAtDeadline() {
        AiAdviceTrack t=paper("TRACKING",minute-300*60_000,minute-299*60_000);
        List<double[]> rows=new ArrayList<>();
        for(long ms=minute-300*60_000;ms<minute;ms+=60_000)rows.add(new double[]{ms,102,98,100});
        // The bar starting at TTL closes one minute too late; its low must not stop the trade.
        rows.set(241,new double[]{minute-59*60_000,102,90,92});
        serve(rows); tracker.settle();
        assertThat(t.getStatus()).isEqualTo("EXPIRED");
        assertThat(t.getResultPct()).isZero();
    }

    @Test void persistedEntryBarStopMustRemainConservativeAfterRestart() {
        AiAdviceTrack t=paper("TRACKING",minute-5*60_000,minute-4*60_000);
        ReflectionTestUtils.invokeMethod(tracker,"settleOne",t,List.of(
                new double[]{minute-4*60_000,111,94,100},new double[]{minute-3*60_000,111,99,110}));
        assertThat(t.getStatus()).isEqualTo("LOSS");
    }

    @Test void unorderedIdenticalDuplicatesMustNormalizeToOneChronologicalStream() throws Exception {
        AiAdviceTrack t=paper("TRACKING",minute-4*60_000,minute-3*60_000);
        JSONArray rows=new JSONArray();
        for(long ms:new long[]{minute-60_000,minute-3*60_000,minute-2*60_000,minute-2*60_000})
            rows.put(new JSONArray().put(Long.toString(ms)).put("100").put("102").put("98").put("100").put("1"));
        when(bybit.getPublicRaw(anyString(),anyMap())).thenReturn(
                new JSONObject().put("retCode",0).put("result",new JSONObject().put("list",rows)).toString());
        List<double[]> parsed=ReflectionTestUtils.invokeMethod(tracker,"fetchCandles","BTCUSDT",time(minute-4*60_000),minute);
        assertThat(parsed).hasSize(3);
        assertThat(parsed.stream().map(r->(long)r[0]).toList()).containsExactly(minute-3*60_000,minute-2*60_000,minute-60_000);
        tracker.settle();
        assertThat(t.getStatus()).isEqualTo("TRACKING");
    }

    @Test void conflictingDuplicateMustRefuseToInventASettlement() throws Exception {
        AiAdviceTrack t=paper("TRACKING",minute-4*60_000,minute-3*60_000);
        JSONArray rows=new JSONArray();
        for(long ms:new long[]{minute-60_000,minute-3*60_000,minute-2*60_000})
            rows.put(new JSONArray().put(Long.toString(ms)).put("100").put("102").put("98").put("100").put("1"));
        rows.put(new JSONArray().put(Long.toString(minute-2*60_000)).put("100").put("102").put("94").put("100").put("1"));
        when(bybit.getPublicRaw(anyString(),anyMap())).thenReturn(
                new JSONObject().put("retCode",0).put("result",new JSONObject().put("list",rows)).toString());
        tracker.settle();
        assertThat(t.getStatus()).isEqualTo("TRACKING");
        verify(repository,never()).save(any());
    }
}
